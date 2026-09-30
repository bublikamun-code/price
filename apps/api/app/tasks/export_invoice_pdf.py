"""Рендер PDF счёта на оплату (Celery). ARCHITECTURE_PLAN.md §10, §16 п.40.

Задача ставится ``POST /api/v2/manager/orders/{orderId}/invoice`` и
``POST /api/v2/manager/invoices/{invoiceId}/pdf`` **после** коммита транзакции
выдачи счёта: воркер читает уже закоммиченную строку, поэтому никогда не
рендерит счёт, который мог быть откачен.

Пайплайн:
  invoice + order + позиции + организация из БД
  → ``app/templates/pdf/invoice.j2`` (weasyprint)
  → S3 ``pdf-catalogs/invoices/invoice-{seq}.pdf``
  → ``FileAsset(type=INVOICE_PDF, order_id, visibility=AUTHED)``
  → ``invoice.pdf_status=READY`` + ``pdf_file_asset_id``.

Состояние рендера — колонка ``invoices.pdf_status``, а НЕ Redis-job (§10):
счёт постоянный документ, TTL записи в Redis и lifecycle бакета
``csv-exports/`` его бы убили. Ошибка → ``FAILED`` + warning в лог, перерендер
через ``POST .../pdf``; поэтому слепой авто-ретрай (``autoretry_for=()``) здесь
неуместен — он просто повторял бы уже упавший рендер.
"""
from __future__ import annotations

import asyncio
import io
import uuid

from app.core.logging import get_logger
from app.models.enums import InvoicePdfStatus
from app.models.invoice import Invoice
from app.repositories import orders as orders_repo
from app.repositories import organizations as organizations_repo
from app.services import storage
from app.services.invoice import invoice_pdf_asset
from app.tasks._common import create_worker_db
from app.workers import celery_app

log = get_logger("app.tasks.export_invoice_pdf")

# Отдельный движок для Celery-задач (NullPool — каждая задача в своём
# asyncio.run; тесты подменяют _worker_session на свой sessionmaker).
_worker_engine, _worker_session = create_worker_db()


@celery_app.task(bind=True, name="render_invoice_pdf", autoretry_for=())
def render_invoice_pdf(self, invoice_id: str, **kwargs) -> dict:
    """Рендер PDF счёта. Оборачивает async-пайплайн; ошибка → FAILED."""
    invoice_uuid = uuid.UUID(invoice_id)
    try:
        return asyncio.run(_render_invoice_pdf(invoice_uuid))
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception(
            "invoice_pdf.crashed", invoice=str(invoice_uuid), error=str(exc)
        )
        asyncio.run(_mark_failed(invoice_uuid, str(exc)))
        return {"invoice_id": str(invoice_uuid), "pdf_status": "FAILED", "error": str(exc)}


async def _render_invoice_pdf(invoice_id: uuid.UUID) -> dict:
    from app.core.config import settings

    async with _worker_session() as db:
        invoice = await db.get(Invoice, invoice_id)
        if invoice is None:
            return {
                "invoice_id": str(invoice_id),
                "pdf_status": "FAILED",
                "error": "Счёт не найден",
            }
        order = await orders_repo.get_order(db, order_id=invoice.order_id)
        if order is None:
            raise RuntimeError(f"Заказ {invoice.order_id} счёта не найден")
        items = await orders_repo.get_order_items(db, order_id=order.id)
        organization = (
            await organizations_repo.get_organization(
                db, organization_id=order.organization_id
            )
            if order.organization_id is not None
            else None
        )

        # Рендер CPU-bound (weasyprint) — в отдельном потоке, чтобы не
        # блокировать event loop воркера.
        body = await asyncio.to_thread(
            _to_pdf_bytes,
            invoice=invoice,
            order=order,
            items=items,
            organization=organization,
        )

        key = f"invoices/invoice-{invoice.seq}.pdf"
        await asyncio.to_thread(
            storage.upload_fileobj,
            settings.s3_bucket_pdfs,
            key,
            io.BytesIO(body),
            content_type="application/pdf",
        )

        asset = invoice_pdf_asset(
            invoice=invoice,
            order=order,
            s3_key=key,
            size_bytes=len(body),
        )
        db.add(asset)
        await db.flush()

        invoice.pdf_status = InvoicePdfStatus.READY
        invoice.pdf_file_asset_id = asset.id
        await db.commit()

    log.info(
        "invoice_pdf.done",
        invoice=str(invoice_id),
        order=str(order.id),
        key=key,
        size_bytes=len(body),
    )
    return {"invoice_id": str(invoice_id), "pdf_status": "READY", "s3_key": key}


def _to_pdf_bytes(*, invoice, order, items: list, organization) -> bytes:
    """invoice.j2 → HTML → A4 (weasyprint). Ленивый импорт — рендер только в воркере."""
    from weasyprint import HTML

    from app.core.templates import render_pdf
    from app.schemas.v2.invoices import invoice_buyer, invoice_seller

    rows = []
    for item in items:
        snapshot = item.product_snapshot or {}
        quantity = int(item.quantity)
        price = float(item.unit_price)
        rows.append(
            {
                "sku": snapshot.get("sku", ""),
                "name": snapshot.get("name", ""),
                "qty": quantity,
                "price": f"{price:.2f}",
                "amount": f"{quantity * price:.2f}",
            }
        )

    delivery_parts = [
        order.delivery_address,
        order.delivery_point,
        order.delivery_contact_name,
        order.delivery_phone,
    ]
    delivery = ", ".join(part for part in delivery_parts if part)

    html = render_pdf(
        "invoice.j2",
        number=invoice.number,
        issued_at=invoice.issued_at.strftime("%d.%m.%Y") if invoice.issued_at else "",
        due_at=invoice.due_at.strftime("%d.%m.%Y") if invoice.due_at else "",
        order_no=f"{order.seq}" if order.seq else "—",
        currency=invoice.currency_code or "BYN",
        total=f"{float(invoice.total_amount):.2f}",
        rows=rows,
        delivery=delivery,
        buyer=invoice_buyer(organization),
        seller=invoice_seller(),
    )
    return HTML(string=html).write_pdf()


async def _mark_failed(invoice_id: uuid.UUID, message: str) -> None:
    """Перевести счёт в ``FAILED``, чтобы UI показал кнопку перерендера."""
    async with _worker_session() as db:
        invoice = await db.get(Invoice, invoice_id)
        if invoice is None:
            return
        invoice.pdf_status = InvoicePdfStatus.FAILED
        await db.commit()


__all__ = ["render_invoice_pdf"]
