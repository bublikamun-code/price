"""Сервис публичной SEO-витрины (/api/v1/public). См. §16 п.29.

Состав каталога без цен/остатков/ПДн: бренды, серии, номенклатура серий.

slug серии: модель Series не имеет slug-колонки (slug есть только у брендов),
поэтому серию идентифицируем её UUID — он стабилен, URL-safe и возвращается
фронту в деталке бренда (PublicSeriesOut.slug), дальше ходит по кругу как
непрозрачный токен: /public/series/{slug}/products.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Series
from app.repositories import public as public_repo
from app.schemas.public import (
    PublicBrandDetailOut,
    PublicBrandOut,
    PublicSeriesOut,
    PublicSeriesProductOut,
)


class NotFoundError(ValueError):
    """Бренд/серия не найдены → 404."""


def _series_out(s: Series) -> PublicSeriesOut:
    """Миниатюра следует конвенции photo-ZIP/ручной заливки: {stem}_thumb.webp."""
    photo_key = s.photo_key
    if photo_key and photo_key.endswith(".webp"):
        thumb = photo_key.replace(".webp", "_thumb.webp")
    else:
        thumb = photo_key
    return PublicSeriesOut(id=s.id, name=s.name, slug=str(s.id), photo_thumb=thumb)


class PublicCatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_brands(self) -> list[PublicBrandOut]:
        brands = await public_repo.fetch_brands(self.db)
        out = []
        for b in brands:
            stats = await public_repo.fetch_brand_stats(self.db, b.id)
            out.append(
                PublicBrandOut(
                    id=b.id,
                    name=b.name,
                    slug=b.slug,
                    photo=stats["photo"],
                    series_count=stats["series_count"],
                    products_count=stats["products_count"],
                )
            )
        return out

    async def get_brand(self, slug: str) -> PublicBrandDetailOut:
        brand = await public_repo.get_brand_by_slug(self.db, slug)
        if brand is None:
            raise NotFoundError("Бренд не найден")
        # Одна AsyncSession не поддерживает параллельные операции, поэтому
        # два независимых чтения выполняем последовательно в прежнем порядке.
        series = await public_repo.fetch_brand_series(self.db, brand_id=brand.id)
        stats = await public_repo.fetch_brand_stats(self.db, brand.id)
        return PublicBrandDetailOut(
            id=brand.id,
            name=brand.name,
            slug=brand.slug,
            photo=stats["photo"],
            series_count=stats["series_count"],
            products_count=stats["products_count"],
            series=[_series_out(s) for s in series],
        )

    async def series_products(
        self, slug: str, *, page: int, per_page: int
    ) -> tuple[list[PublicSeriesProductOut], int]:
        try:
            series_id = uuid.UUID(slug)
        except ValueError as exc:
            raise NotFoundError("Серия не найдена") from exc
        series = await public_repo.get_series(self.db, series_id)
        if series is None:
            raise NotFoundError("Серия не найдена")
        total = await public_repo.count_series_products(self.db, series_id=series.id)
        rows = await public_repo.fetch_series_products(
            self.db,
            series_id=series.id,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        items = [
            PublicSeriesProductOut(sku=p.sku, name=p.name, photo=photo_key)
            for p, photo_key in rows
        ]
        return items, total
