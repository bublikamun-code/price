"""Репозиторий клиентского дашборда. См. §6, §16 п.20.

Только запросы (агрегаты по данным текущего пользователя). Дневные бакеты —
по календарю Europe/Minsk (как в manager_catalog, §20). Скоуп всех выборок —
client_id текущего пользователя.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import PriceHistory, Product, Series
from app.models.enums import OrderStatus
from app.models.order import Order, OrderItem
from app.models.user import Favorite

# Часовой пояс дневных бакетов дашборда (см. celery beat, §20).
MINSK_TZ = "Europe/Minsk"

# «В работе» — заявки, требующие действий клиента/менеджера (как на фронте).
ACTIVE_STATUSES = (OrderStatus.NEW, OrderStatus.IN_PROGRESS)


def _minsk_day(column):
    """Локальная календарная дата колонки-таймстемпа по Europe/Minsk."""
    return func.date(func.timezone(MINSK_TZ, column))


# ------------------------------------------------------------- дашборд клиента

async def fetch_client_kpi(
    db: AsyncSession, *, client_id: uuid.UUID, month_start: date
) -> tuple[int, int, Decimal]:
    """(всего заявок без CANCELLED, за текущий месяц, Σ total_amount) клиента."""
    base = [Order.client_id == client_id, Order.status != OrderStatus.CANCELLED]
    orders_total = await db.scalar(select(func.count(Order.id)).where(*base))
    day = _minsk_day(Order.created_at)
    orders_month = await db.scalar(
        select(func.count(Order.id)).where(*base, day >= month_start)
    )
    spent = await db.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(*base)
    )
    return int(orders_total or 0), int(orders_month or 0), Decimal(str(spent or 0))


async def fetch_orders_by_day(
    db: AsyncSession, *, client_id: uuid.UUID, start_day: date
) -> dict[date, int]:
    """Число заявок клиента по дням (дата Минска) от ``start_day`` включительно."""
    day = _minsk_day(Order.created_at).label("day")
    rows = await db.execute(
        select(day, func.count(Order.id).label("cnt"))
        .where(Order.client_id == client_id, day >= start_day)
        .group_by(day)
    )
    return {row.day: int(row.cnt) for row in rows.all()}


async def fetch_status_counts(db: AsyncSession, *, client_id: uuid.UUID) -> list:
    """Число заявок клиента по статусам (все статусы, убывание по счётчику)."""
    rows = await db.execute(
        select(Order.status.label("status"), func.count(Order.id).label("cnt"))
        .where(Order.client_id == client_id)
        .group_by(Order.status)
        .order_by(func.count(Order.id).desc(), Order.status.asc())
    )
    return list(rows.all())


async def fetch_top_products(
    db: AsyncSession, *, client_id: uuid.UUID, limit: int = 5
) -> list:
    """Топ товаров клиента по количеству (без CANCELLED) с суммой по позициям."""
    qty = func.sum(OrderItem.quantity).label("qty")
    revenue = func.sum(OrderItem.unit_price * OrderItem.quantity).label("revenue")
    stmt = (
        select(
            OrderItem.product_id.label("product_id"),
            Product.sku.label("sku"),
            Product.name.label("name"),
            qty,
            revenue,
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.client_id == client_id, Order.status != OrderStatus.CANCELLED)
        .group_by(OrderItem.product_id, Product.sku, Product.name)
        .order_by(qty.desc(), revenue.desc(), Product.sku.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_recent_orders(
    db: AsyncSession, *, client_id: uuid.UUID, limit: int = 5
) -> list:
    """Последние заявки клиента (новые первыми, любой статус)."""
    stmt = (
        select(Order.id, Order.created_at, Order.status, Order.total_amount, Order.seq)
        .where(Order.client_id == client_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_active_orders(
    db: AsyncSession, *, client_id: uuid.UUID, limit: int = 10
) -> list:
    """Активные заявки клиента (NEW/IN_PROGRESS, новые первыми)."""
    stmt = (
        select(Order.id, Order.created_at, Order.status, Order.total_amount, Order.seq)
        .where(Order.client_id == client_id, Order.status.in_(ACTIVE_STATUSES))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_last_order_id(
    db: AsyncSession, *, client_id: uuid.UUID
) -> uuid.UUID | None:
    """id последней заявки клиента (любой статус) — для quick_actions."""
    return await db.scalar(
        select(Order.id)
        .where(Order.client_id == client_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(1)
    )


async def fetch_favorite_products(
    db: AsyncSession, *, user_id: uuid.UUID, limit: int = 10
) -> list:
    """Избранное клиента: не удалённые товары + photo_key серии (фото крепится
    к серии, см. §3 ТЗ). Источник блока «Изменения цен в избранном»."""
    stmt = (
        select(Product, Series.photo_key.label("photo_key"))
        .select_from(Favorite)
        .join(Product, Product.id == Favorite.product_id)
        .outerjoin(Series, Series.id == Product.series_id)
        .where(Favorite.user_id == user_id, Product.deleted_at.is_(None))
        .order_by(Favorite.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_last_price_history(
    db: AsyncSession, *, product_id: uuid.UUID, limit: int = 2
) -> list[PriceHistory]:
    """Последние ``limit`` записей истории цены товара (новые первыми)."""
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.changed_at.desc(), PriceHistory.id.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def fetch_new_arrivals(db: AsyncSession, *, limit: int = 5) -> list:
    """Последние не удалённые товары каталога (+ photo_key серии)."""
    stmt = (
        select(Product, Series.photo_key.label("photo_key"))
        .select_from(Product)
        .outerjoin(Series, Series.id == Product.series_id)
        .where(Product.deleted_at.is_(None))
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_promos(db: AsyncSession, *, limit: int = 10) -> list:
    """Товары со скидкой клиента (персональная фиксированная цена, §8/§17).

    Источник блока «Акции» клиентского дашборда: override_price NOT NULL —
    цена по договору ниже базовой розницы.
    """
    stmt = (
        select(Product, Series.photo_key.label("photo_key"))
        .select_from(Product)
        .outerjoin(Series, Series.id == Product.series_id)
        .where(
            Product.deleted_at.is_(None),
            Product.override_price.is_not(None),
            Product.override_valid_until.is_(None)
            | (Product.override_valid_until > func.now()),
        )
        .order_by(Product.updated_at.desc(), Product.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())
