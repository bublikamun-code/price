"""Репозиторий публичной SEO-витрины (/api/v1/public). См. §16 п.29.

Правила видимости товаров — как в каталоге (repositories/catalog.py):
``deleted_at IS NULL`` и ``stock_status != ARCHIVED``.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, Product, Series
from app.models.enums import StockStatus


async def fetch_brands(db: AsyncSession) -> list[Brand]:
    res = await db.execute(select(Brand).order_by(Brand.name))
    return list(res.scalars().all())


async def get_brand_by_slug(db: AsyncSession, slug: str) -> Brand | None:
    return await db.scalar(select(Brand).where(Brand.slug == slug))


async def fetch_brand_series(db: AsyncSession, *, brand_id: uuid.UUID) -> list[Series]:
    res = await db.execute(
        select(Series).where(Series.brand_id == brand_id).order_by(Series.name)
    )
    return list(res.scalars().all())


async def get_series(db: AsyncSession, series_id: uuid.UUID) -> Series | None:
    return await db.get(Series, series_id)


def _visible_products_stmt(series_id: uuid.UUID):
    """Базовый stmt видимых товаров серии (копия правил каталога §7)."""
    return select(Product).where(
        Product.series_id == series_id,
        Product.deleted_at.is_(None),
        Product.stock_status != StockStatus.ARCHIVED,
    )


async def count_series_products(db: AsyncSession, *, series_id: uuid.UUID) -> int:
    stmt = select(func.count(Product.id)).where(
        Product.series_id == series_id,
        Product.deleted_at.is_(None),
        Product.stock_status != StockStatus.ARCHIVED,
    )
    return int(await db.scalar(stmt) or 0)


async def fetch_series_products(
    db: AsyncSession, *, series_id: uuid.UUID, limit: int, offset: int
) -> list[Product]:
    stmt = _visible_products_stmt(series_id).order_by(Product.name).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def fetch_brand_stats(db: AsyncSession, brand_id: uuid.UUID) -> dict:
    """Витрина бренда: число серий/товаров + первое фото товара (лендинг)."""
    from sqlalchemy import func, select

    from app.models.catalog import Product, ProductPhoto, Series

    series_count = (
        await db.scalar(
            select(func.count()).select_from(Series).where(Series.brand_id == brand_id)
        )
    ) or 0
    visible = Product.deleted_at.is_(None), Product.brand_id == brand_id
    products_count = (
        await db.scalar(select(func.count()).select_from(Product).where(*visible))
    ) or 0
    photo = await db.scalar(
        select(ProductPhoto.photo_key)
        .join(Product, Product.id == ProductPhoto.product_id)
        .where(*visible)
        .order_by(ProductPhoto.sort_order, ProductPhoto.created_at)
        .limit(1)
    )
    if photo is None:
        # фолбэк: фото серии (KEAZ — обработанный webp витрины)
        photo = await db.scalar(
            select(Series.photo_key)
            .where(Series.brand_id == brand_id, Series.photo_key.is_not(None))
            .limit(1)
        )
    return {"series_count": series_count, "products_count": products_count, "photo": photo}
