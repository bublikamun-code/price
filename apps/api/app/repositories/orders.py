"""Репозиторий заявок. См. ARCHITECTURE_PLAN.md §9."""
import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models.enums import OrderStatus
from app.models.order import Order, OrderIdempotency, OrderItem
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
    organization_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    stmt = select(Order)
    if organization_id is not None:
        legacy_filter = (
            Order.organization_id.is_(None) & (Order.client_id == client_id)
            if client_id is not None
            else Order.organization_id.is_(None)
        )
        stmt = stmt.where(or_(Order.organization_id == organization_id, legacy_filter))
    elif client_id is not None:
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
    organization_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
) -> int:
    stmt = select(func.count(Order.id))
    if organization_id is not None:
        legacy_filter = (
            Order.organization_id.is_(None) & (Order.client_id == client_id)
            if client_id is not None
            else Order.organization_id.is_(None)
        )
        stmt = stmt.where(or_(Order.organization_id == organization_id, legacy_filter))
    elif client_id is not None:
        stmt = stmt.where(Order.client_id == client_id)
    if manager_id is not None:
        stmt = stmt.where(Order.manager_id == manager_id)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return int(await db.scalar(stmt) or 0)


def _v2_scope_filter(*, client_id: uuid.UUID, organization_id: uuid.UUID | None):
    """Commercial visibility for the authenticated client v2 collection.

    In USER scope only the caller's legacy/NULL-organization orders are visible.
    In ORGANIZATION scope all orders owned by the selected organization are
    visible, plus the caller's legacy/NULL-organization compatibility orders.
    This predicate is intentionally separate from the v1 fetch/count methods:
    their offset and legacy behavior must remain untouched.
    """
    if organization_id is None:
        return and_(Order.client_id == client_id, Order.organization_id.is_(None))
    return or_(
        Order.organization_id == organization_id,
        and_(Order.organization_id.is_(None), Order.client_id == client_id),
    )


async def fetch_orders_v2_page(
    db: AsyncSession,
    *,
    client_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    status: OrderStatus | None = None,
    limit: int,
    after: dict[str, str] | None = None,
) -> list[Order]:
    """Fetch a bounded, stable keyset page without loading order items."""
    stmt = select(Order).options(
        load_only(
            Order.id,
            Order.seq,
            Order.organization_id,
            Order.client_id,
            Order.status,
            Order.total_amount,
            Order.currency_code,
            Order.exchange_rate,
            Order.rate_source,
            Order.created_at,
            Order.updated_at,
            Order.version,
        )
    )
    stmt = stmt.where(_v2_scope_filter(client_id=client_id, organization_id=organization_id))
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if after is not None:
        after_created_at = datetime.fromisoformat(after["value"])
        after_id = uuid.UUID(after["id"])
        stmt = stmt.where(
            or_(
                Order.created_at < after_created_at,
                and_(Order.created_at == after_created_at, Order.id < after_id),
            )
        )
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_idempotency_record(
    db: AsyncSession, *, user_id: uuid.UUID, idempotency_key: str
) -> OrderIdempotency | None:
    return await db.scalar(
        select(OrderIdempotency).where(
            OrderIdempotency.user_id == user_id,
            OrderIdempotency.idempotency_key == idempotency_key,
        )
    )


async def add_idempotency_record(
    db: AsyncSession, *, record: OrderIdempotency
) -> OrderIdempotency:
    db.add(record)
    await db.flush()
    return record


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
