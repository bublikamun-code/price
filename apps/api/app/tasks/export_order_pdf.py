"""PDF-выгрузка заявки (Celery). §16 п.25, фича F.

Контракт: ``services.export.start_order_pdf`` диспатчит ``run_order_pdf``
(job ``QUEUED`` в Redis ``export:job:{id}``); здесь:
  RUNNING → заказ + позиции + клиент из БД → шаблон ``app/templates/pdf/order.j2``
  → weasyprint → S3 ``csv-exports`` ``export/{job_id}.pdf`` → DONE (s3_key).

Надёжность — по образцу ``tasks/export_catalog.py``: слепой авто-ретрай
отключён, критическая ошибка фиксирует FAILED и пишется в лог.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.order import Order, OrderItem
from app.models.user import User
from app.services import storage
from app.tasks._common import create_worker_db, mark_redis_job_failed
from app.workers import celery_app

log = get_logger("app.tasks.export_order_pdf")

# Отдельный движок для Celery-задач (NullPool — каждая задача в своём
# asyncio.run); тесты подменяют _worker_session на свой sessionmaker.
_worker_engine, _worker_session = create_worker_db()


@celery_app.task(bind=True, name="export_order_pdf", autoretry_for=())
def run_order_pdf(self, job_id: str, order_id: str, **kwargs) -> dict:
    """Запуск PDF-выгрузки заявки. Оборачивает async-пайплайн."""
    try:
        return asyncio.run(_run_order_pdf(uuid.UUID(job_id), uuid.UUID(order_id)))
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception("order_pdf.crashed", job_id=job_id, error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}


async def _run_order_pdf(job_id: uuid.UUID, order_id: uuid.UUID) -> dict:
    from app.services.export import STATUS_DONE, STATUS_RUNNING, set_job_state

    await set_job_state(
        job_id, status=STATUS_RUNNING, started_at=datetime.now(UTC).isoformat()
    )

    async with _worker_session() as db:
        order = await db.get(Order, order_id)
        if order is None:
            await set_job_state(job_id, status="FAILED", error="Заявка не найдена")
            return {"job_id": str(job_id), "status": "FAILED", "error": "Заявка не найдена"}

        from app.repositories import orders as orders_repo  # lazy: цикличность

        items = await orders_repo.get_order_items(db, order_id=order.id)
        client = await db.get(User, order.client_id)

        body = await asyncio.to_thread(
            _to_pdf_bytes, order=order, client=client, items=items
        )

    key = f"export/{job_id}.pdf"
    storage.upload_fileobj(
        settings_bucket(), key, io.BytesIO(body), content_type="application/pdf",
    )
    await set_job_state(job_id, status=STATUS_DONE, s3_key=key)
    log.info("order_pdf.done", job_id=str(job_id), order=str(order_id), key=key)
    return {"job_id": str(job_id), "status": STATUS_DONE}


def settings_bucket() -> str:
    from app.core.config import settings

    return settings.s3_bucket_exports


def _to_pdf_bytes(*, order, client, items: list[OrderItem]) -> bytes:
    """order.j2 → HTML → A4 (weasyprint). Ленивый импорт — рендер только в воркере."""
    from weasyprint import HTML

    from app.core.templates import render_pdf
    from app.services.email import DELIVERY_METHOD_RU, format_order_no

    rows = []
    total = 0.0
    for i in items:
        snap = i.product_snapshot or {}
        qty = int(i.quantity)
        price = float(i.unit_price)
        amount = round(qty * price, 2)
        total += amount
        rows.append({
            "sku": snap.get("sku", ""),
            "name": snap.get("name", ""),
            "qty": qty,
            "price": f"{price:.2f}",
            "amount": f"{amount:.2f}",
        })

    delivery = DELIVERY_METHOD_RU.get(order.delivery_method or "", "")
    if order.delivery_method == "delivery" and order.delivery_point:
        delivery = f"{delivery} ({order.delivery_point})"

    html = render_pdf(
        "order.j2",
        order_no=format_order_no(order.seq),
        date=order.created_at.strftime("%d.%m.%Y") if order.created_at else "",
        client_name=(client.full_name if client else "") or "",
        client_company=(client.company if client else "") or "",
        delivery=delivery,
        comment=order.notes or "",
        currency=order.currency_code or "BYN",
        rate=float(order.exchange_rate or 1),
        total=f"{float(order.total_amount):.2f}",
        rows=rows,
    )
    return HTML(string=html).write_pdf()


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    await mark_redis_job_failed("app.services.export", job_id, message)
