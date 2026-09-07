"""Репозиторий заявок. См. ARCHITECTURE_PLAN.md §9."""
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus
from app.models.order import Order, OrderItem
from app.models.user import User

# PG-последовательность сквозных номеров (создаётся миграцией 0009;
# ORM-декларация — app.models.order.orders_seq_numbering).
ORDERS_SEQ_NAME = "orders_seq_seq"


async def get_order(db: AsyncSession, *, order_id: uuid.UUID) -> Order | None:
    return await db.scalar(select(Order).where(Order.id == order_id))


async def next_order_seq(db: AsyncSession) -> int:
    """Следующий сквозной номер заявки: nextval('orders_seq_seq').

    Ранее было MAX(seq)+1: два конкурентных оформления получали один номер и
    второй падал по ``uq_orders_seq`` с 500 (аудит 2026-09-06). nextval
    атомарен и не блокируется — дубли невозможны в принципе. «Дыры» в
    нумерации при откате транзакции допустимы (номер сквозной, не
    бухгалтерский).
    """
    return int(await db.scalar(text(f"SELECT nextval('{ORDERS_SEQ_NAME}')")))


async def fetch_users_by_ids(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, User]:
    """Map id → User одним запросом (для показа имён клиентов в списке заявок)."""
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    res = await db.execute(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in res.scalars().all()}


async def fetch_orders(
    db: AsyncSession,
    *,
    client_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    stmt = select(Order)
    if client_id is not None:
        stmt = stmt.where(Order.client_id == client_id)
    if manager_id is not None:
        stmt = stmt.where(Order.manager_id == manager_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def count_orders(
    db: AsyncSession,
    *,
    client_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
) -> int:
    stmt = select(func.count(Order.id))
    if client_id is not None:
        stmt = stmt.where(Order.client_id == client_id)
    if manager_id is not None:
        stmt = stmt.where(Order.manager_id == manager_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return int(await db.scalar(stmt) or 0)


async def get_order_items(db: AsyncSession, *, order_id: uuid.UUID) -> list[OrderItem]:
    res = await db.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.created_at)
    )
    return list(res.scalars().all())


async def create_order(db: AsyncSession, *, order: Order) -> Order:
    db.add(order)
    await db.flush()
    return order


async def add_order_items(db: AsyncSession, *, items: list[OrderItem]) -> None:
    db.add_all(items)
    await db.flush()


async def update_order_status(
    db: AsyncSession,
    *,
    order: Order,
    new_status: OrderStatus,
    manager_id: uuid.UUID | None = None,
) -> Order:
    order.status = new_status
    if manager_id is not None:
        order.manager_id = manager_id
    await db.flush()
    return order
