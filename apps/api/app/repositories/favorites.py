"""Репозиторий избранного. См. ARCHITECTURE_PLAN.md §16.1 (фича A)."""
import uuid
from sqlalchemy import select, func, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import Favorite
from app.models.catalog import Brand, Product, Series


async def fetch_favorites(db: AsyncSession, *, user_id: uuid.UUID, limit: int = 50, offset: int = 0):
    """Возвращает ``list[Row]`` с полями favorite + product + brand_name + photo_key.

    Поля ``Product`` (sku, name, base_price, override_price, stock_status, ...)
    доступны как ``row[1]``; ``Favorite`` — как ``row[0]``. Доп. колонки:
    ``brand_name`` (из Brand) и ``photo_key`` (из Series — фото крепится к серии,
    см. §3 ТЗ; у самого Product поля photo_key нет).

    JOIN (по образцу ``catalog.fetch_catalog``):
        Favorite → Product  (Favorite.product_id == Product.id, outerjoin)
        Product → Brand     (Product.brand_id == Brand.id,     outerjoin — brand_id nullable)
        Product → Series    (Product.series_id == Series.id,   outerjoin — для photo_key)

    Архивные/удалённые товары НЕ отфильтровываются: избранное — пользовательский
    список, фронт показывает бейдж «нет в наличии» (§16.1 фича A). Это же источник
    для ``PRICE_CHANGED_DIGEST`` (§20) — нужно видеть изменение цены даже у ушедших
    из каталога позиций.
    """
    stmt = (
        select(
            Favorite,
            Product,
            Brand.name.label("brand_name"),
            Series.photo_key.label("photo_key"),
        )
        .outerjoin(Product, Product.id == Favorite.product_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .outerjoin(Series, Series.id == Product.series_id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.all()


async def count_favorites(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(Favorite).where(Favorite.user_id == user_id)) or 0)


async def add_favorite(db: AsyncSession, *, user_id: uuid.UUID, product_id: uuid.UUID) -> None:
    """Idempotent: INSERT ... ON CONFLICT (user_id, product_id) DO NOTHING."""
    stmt = pg_insert(Favorite).values(user_id=user_id, product_id=product_id)
    # Конфликт разрешаем по составному PK (user_id, product_id) — имя uq-констрейнта
    # в БД может отсутствовать, поэтому ориентируемся на колонки.
    stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "product_id"])
    await db.execute(stmt)
    await db.flush()


async def delete_favorite(db: AsyncSession, *, user_id: uuid.UUID, product_id: uuid.UUID) -> bool:
    res = await db.execute(delete(Favorite).where(Favorite.user_id == user_id, Favorite.product_id == product_id))
    return (res.rowcount or 0) > 0


async def is_favorite(db: AsyncSession, *, user_id: uuid.UUID, product_id: uuid.UUID) -> bool:
    found = await db.scalar(select(func.count()).select_from(Favorite).where(Favorite.user_id == user_id, Favorite.product_id == product_id))
    return (found or 0) > 0
