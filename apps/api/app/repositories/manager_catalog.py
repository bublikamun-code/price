"""Репозиторий менеджер-панели: дашборд, товары, бренды. См. §6, §16 п.20.

Только запросы (чтение/aggregation + write-хелперы брендов); правила и
транзакции — в сервисах. Дневные бакеты дашборда — по календарю Europe/Minsk
(как celery beat, §20), единообразно для KPI и графика.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, PriceListVersion, Product, Series
from app.models.enums import (
    OrderStatus,
    PriceListVersionStatus,
    StockStatus,
    UserRole,
)
from app.models.order import Order, OrderItem
from app.models.user import User

# Часовой пояс дневных бакетов дашборда (см. celery beat, §20).
MINSK_TZ = "Europe/Minsk"


def _minsk_day(column):
    """Локальная календарная дата колонки-таймстемпа по Europe/Minsk."""
    return func.date(func.timezone(MINSK_TZ, column))


def _client_name_expr():
    """Имя клиента в выборках: компания, иначе ФИО (непустое)."""
    return func.coalesce(func.nullif(User.company, ""), User.full_name)


def _not_cancelled_month(month_start: date) -> list:
    """Фильтр выручки: заказы текущего календарного месяца (дата Минска),
    кроме CANCELLED — общий для revenue_month и топов (§16 п.20-1)."""
    return [
        Order.status != OrderStatus.CANCELLED,
        _minsk_day(Order.created_at) >= month_start,
    ]


# ------------------------------------------------------------- дашборд (G)

async def fetch_orders_counts(db: AsyncSession, *, today: date, week_start: date) -> tuple[int, int]:
    """Заказы сегодня / за 7 календарных дней (включая сегодня), по дате Минска."""
    day = _minsk_day(Order.created_at)
    today_cnt = await db.scalar(select(func.count(Order.id)).where(day == today))
    week_cnt = await db.scalar(select(func.count(Order.id)).where(day >= week_start))
    return int(today_cnt or 0), int(week_cnt or 0)


async def fetch_revenue_month(db: AsyncSession, *, month_start: date) -> Decimal:
    """Σ(unit_price × quantity) по заказам месяца без CANCELLED."""
    stmt = (
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0))
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(*_not_cancelled_month(month_start))
    )
    return Decimal(str(await db.scalar(stmt) or 0))


async def fetch_new_clients_count(db: AsyncSession, *, threshold: datetime) -> int:
    """Клиенты, созданные не раньше ``threshold`` (UTC)."""
    cnt = await db.scalar(
        select(func.count(User.id)).where(
            User.role == UserRole.CLIENT, User.created_at >= threshold
        )
    )
    return int(cnt or 0)


async def fetch_active_imports_count(db: AsyncSession) -> int:
    """Версии прайса в работе: QUEUED или PROCESSING."""
    cnt = await db.scalar(
        select(func.count(PriceListVersion.id)).where(
            PriceListVersion.status.in_(
                (PriceListVersionStatus.QUEUED, PriceListVersionStatus.PROCESSING)
            )
        )
    )
    return int(cnt or 0)


async def fetch_orders_by_day(db: AsyncSession, *, start_day: date) -> dict[date, int]:
    """Число заказов по дням (дата Минска) от ``start_day`` включительно."""
    day = _minsk_day(Order.created_at).label("day")
    rows = await db.execute(
        select(day, func.count(Order.id).label("cnt")).where(day >= start_day).group_by(day)
    )
    return {row.day: int(row.cnt) for row in rows.all()}


async def fetch_top_products(db: AsyncSession, *, month_start: date, limit: int = 5) -> list:
    """Топ товаров по выручке месяца (без CANCELLED)."""
    revenue = func.sum(OrderItem.unit_price * OrderItem.quantity).label("revenue")
    stmt = (
        select(
            OrderItem.product_id.label("product_id"),
            Product.sku.label("sku"),
            Product.name.label("name"),
            func.sum(OrderItem.quantity).label("qty"),
            revenue,
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(*_not_cancelled_month(month_start))
        .group_by(OrderItem.product_id, Product.sku, Product.name)
        .order_by(revenue.desc(), Product.sku.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_top_clients(db: AsyncSession, *, month_start: date, limit: int = 5) -> list:
    """Топ клиентов по выручке месяца (без CANCELLED).

    OrderItem — LEFT JOIN: заказ без позиций всё равно даёт +1 к числу
    заказов клиента (выручка от NULL-строк в sum не попадает).
    """
    name_expr = _client_name_expr().label("name")
    revenue = (
        func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0).label("revenue")
    )
    stmt = (
        select(
            User.id.label("client_id"),
            name_expr,
            func.count(func.distinct(Order.id)).label("orders"),
            revenue,
        )
        .select_from(Order)
        .join(User, User.id == Order.client_id)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(*_not_cancelled_month(month_start))
        .group_by(User.id, User.company, User.full_name)
        .order_by(revenue.desc(), User.id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def fetch_recent_orders(db: AsyncSession, *, limit: int = 5) -> list:
    """Последние заказы (новые первыми) с именем клиента."""
    name_expr = _client_name_expr().label("client_name")
    stmt = (
        select(
            Order.id,
            Order.created_at,
            name_expr,
            Order.status,
            Order.total_amount,
        )
        .select_from(Order)
        .join(User, User.id == Order.client_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


# ------------------------------------------------------- товары менеджера (п.20-2)

def _manager_product_conditions(
    q: str | None, brand_id: uuid.UUID | None, stock: StockStatus | None
) -> list:
    """WHERE менеджерского списка: только не удалённые + фильтры.

    В отличие от клиентского каталога, ARCHIVED виден (менеджер управляет
    статусом), поиск по sku/name — как в repositories/catalog.fetch_catalog.
    """
    conditions = [Product.deleted_at.is_(None)]
    if q:
        pat = f"%{q}%"
        conditions.append(or_(Product.sku.ilike(pat), Product.name.ilike(pat)))
    if brand_id is not None:
        conditions.append(Product.brand_id == brand_id)
    if stock is not None:
        conditions.append(Product.stock_status == stock)
    return conditions


def _manager_product_stmt():
    return (
        select(
            Product.id,
            Product.sku,
            Product.name,
            Product.base_price,
            Product.override_price,
            Product.stock_status,
            Brand.id.label("brand_id"),
            Brand.name.label("brand_name"),
            Series.id.label("series_id"),
            Series.name.label("series_name"),
        )
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .outerjoin(Series, Series.id == Product.series_id)
    )


async def fetch_manager_products(
    db: AsyncSession,
    *,
    q: str | None = None,
    brand_id: uuid.UUID | None = None,
    stock: StockStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list, int]:
    """Список товаров для менеджера (сортировка по имени) + общее кол-во."""
    conditions = _manager_product_conditions(q, brand_id, stock)
    rows = (
        await db.execute(
            _manager_product_stmt()
            .where(*conditions)
            .order_by(Product.name.asc(), Product.id.asc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = await db.scalar(select(func.count(Product.id)).where(*conditions))
    return list(rows), int(total or 0)


async def get_manager_product(db: AsyncSession, product_id: uuid.UUID):
    """Строка товара (как в списке) по id, среди не удалённых."""
    return (
        await db.execute(
            _manager_product_stmt().where(
                Product.id == product_id, Product.deleted_at.is_(None)
            )
        )
    ).first()


async def get_active_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    return await db.scalar(
        select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
    )


# ------------------------------------------------------- бренды менеджера (п.20-3)

def _slugify_name(name: str) -> str:
    """Имя → slug как в tasks/photo_zip._norm_stem: lower, ``_``/пробел → ``-``."""
    return name.lower().strip().replace("_", "-").replace(" ", "-")


async def generate_unique_slug(db: AsyncSession, name: str) -> str:
    """Slug из имени; при коллизии — авто-суффикс ``-2``, ``-3``, ..."""
    base = _slugify_name(name)
    if not base:
        raise ValueError("Название бренда должно содержать символы кроме пробелов")
    slug, suffix = base, 2
    while await db.scalar(select(Brand.id).where(Brand.slug == slug)):
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _brands_with_counts_stmt():
    """Бренды + счётчики серий и не удалённых товаров (два подзапроса,
    чтобы избежать веерного произведения серий × товары)."""
    series_cnt = (
        select(Series.brand_id.label("brand_id"), func.count(Series.id).label("cnt"))
        .group_by(Series.brand_id)
        .subquery()
    )
    products_cnt = (
        select(Product.brand_id.label("brand_id"), func.count(Product.id).label("cnt"))
        .where(Product.deleted_at.is_(None))
        .group_by(Product.brand_id)
        .subquery()
    )
    return (
        select(
            Brand.id,
            Brand.name,
            Brand.slug,
            func.coalesce(series_cnt.c.cnt, 0).label("series_count"),
            func.coalesce(products_cnt.c.cnt, 0).label("products_count"),
        )
        .outerjoin(series_cnt, series_cnt.c.brand_id == Brand.id)
        .outerjoin(products_cnt, products_cnt.c.brand_id == Brand.id)
    )


async def fetch_brands_with_counts(db: AsyncSession) -> list:
    stmt = _brands_with_counts_stmt().order_by(Brand.name.asc(), Brand.id.asc())
    return list((await db.execute(stmt)).all())


async def get_brand_with_counts(db: AsyncSession, brand_id: uuid.UUID):
    stmt = _brands_with_counts_stmt().where(Brand.id == brand_id)
    return (await db.execute(stmt)).first()


async def brand_has_children(db: AsyncSession, brand_id: uuid.UUID) -> tuple[bool, bool]:
    """(есть серии, есть не удалённые товары) — guard удаления бренда."""
    series_cnt = await db.scalar(
        select(func.count(Series.id)).where(Series.brand_id == brand_id)
    )
    products_cnt = await db.scalar(
        select(func.count(Product.id)).where(
            Product.brand_id == brand_id, Product.deleted_at.is_(None)
        )
    )
    return int(series_cnt or 0) > 0, int(products_cnt or 0) > 0
