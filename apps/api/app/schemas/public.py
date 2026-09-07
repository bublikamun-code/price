"""DTO публичной SEO-витрины (/api/v1/public). См. §6, SITEMAP §5, §16 п.29.

Без цен/остатков/ПДн: только состав каталога (бренды → серии → номенклатура).
Контракт совпадает с apps/web/pages/brands/*.vue 1-в-1 (фронт разворачивает
конверт через unwrapData).
"""
import uuid

from pydantic import BaseModel

from app.schemas import MetaPage


class PublicBrandOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    # витрина лендинга: представительское фото + счётчики (§16 п.29)
    photo: str | None = None
    series_count: int = 0
    products_count: int = 0


class PublicSeriesOut(BaseModel):
    """Серия в деталке бренда. slug — непрозрачный токен для фронта
    (см. services/public_catalog.py): по нему фронт запрашивает товары серии."""

    id: uuid.UUID
    name: str
    slug: str
    photo_thumb: str | None


class PublicBrandDetailOut(PublicBrandOut):
    series: list[PublicSeriesOut]


class PublicSeriesProductOut(BaseModel):
    sku: str
    name: str


class PublicBrandListEnvelope(BaseModel):
    data: list[PublicBrandOut]


class PublicBrandDetailEnvelope(BaseModel):
    data: PublicBrandDetailOut


class PublicSeriesProductsEnvelope(BaseModel):
    data: list[PublicSeriesProductOut]
    meta: MetaPage
