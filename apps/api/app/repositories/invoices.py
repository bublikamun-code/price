"""Репозиторий счетов на оплату. См. ARCHITECTURE_PLAN.md §5.2, §16 п.40.

Только запросы к БД; правила (1:1 с заказом, заморозка сумм, доменные ошибки) —
в ``services/invoice.py``. Как и соседние репозитории — только ``flush``,
коммитит роутер (§4).
"""
import uuid
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice

# PG-последовательность сквозных номеров счетов (создаётся миграцией 0023;
# ORM-декларация — app.models.invoice.invoices_seq_numbering).
INVOICES_SEQ_NAME = "invoices_seq_seq"


async def next_invoice_seq(db: AsyncSession) -> int:
    """Следующий сквозной номер счёта: nextval('invoices_seq_seq').

    Ровно тот же приём, что у ``next_order_seq``: nextval атомарен, MAX(seq)+1
    падал бы по ``uq_invoices_seq`` при конкурентном выставлении (§16 п.9).
    """
    return int(await db.scalar(text(f"SELECT nextval('{INVOICES_SEQ_NAME}')")))


async def get_invoice(db: AsyncSession, *, invoice_id: uuid.UUID) -> Invoice | None:
    return await db.scalar(select(Invoice).where(Invoice.id == invoice_id))


async def get_invoice_by_order(
    db: AsyncSession, *, order_id: uuid.UUID
) -> Invoice | None:
    """Счёт заказа (их 1:1, поэтому не нужен limit)."""
    return await db.scalar(select(Invoice).where(Invoice.order_id == order_id))


async def fetch_invoices_by_orders(
    db: AsyncSession, *, order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Invoice]:
    """Счета по пачке заказов ОДНИМ запросом — против N+1 в коллекции (§6).

    Возвращает карту ``order_id → Invoice``; заказы без счёта в карте
    отсутствуют (``invoice: null`` в проекции).
    """
    ids = {oid for oid in order_ids if oid is not None}
    if not ids:
        return {}
    rows = await db.execute(select(Invoice).where(Invoice.order_id.in_(ids)))
    return {invoice.order_id: invoice for invoice in rows.scalars().all()}


async def create_invoice(db: AsyncSession, *, invoice: Invoice) -> Invoice:
    db.add(invoice)
    await db.flush()
    return invoice


__all__ = [
    "INVOICES_SEQ_NAME",
    "create_invoice",
    "fetch_invoices_by_orders",
    "get_invoice",
    "get_invoice_by_order",
    "next_invoice_seq",
]
