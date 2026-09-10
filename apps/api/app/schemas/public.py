"""DTO публичной SEO-витрины (/api/v1/public). См. §6, SITEMAP §5, §16 п.29.

Без цен/остатков/ПДн: только состав каталога (бренды → серии → номенклатура).
Контракт совпадает с apps/web/pages/brands/*.vue 1-в-1 (фронт разворачивает
конверт через unwrapData).
"""
import uuid

from pydantic import BaseModel, EmailStr, Field

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
    # личное фото товара (ключ photos-product/…) — витрина лендинга (2026-09-08)
    photo: str | None = None


class PublicBrandListEnvelope(BaseModel):
    data: list[PublicBrandOut]


class PublicBrandDetailEnvelope(BaseModel):
    data: PublicBrandDetailOut


class PublicSeriesProductsEnvelope(BaseModel):
    data: list[PublicSeriesProductOut]
    meta: MetaPage


class PublicLeadIn(BaseModel):
    """Заявка на доступ с лендинга (гость, без авторизации)."""

    company: str = Field(min_length=2, max_length=255)
    contact_name: str = Field(min_length=2, max_length=255)
    phone: str = Field(min_length=7, max_length=32)
    email: EmailStr | None = None
    comment: str | None = Field(default=None, max_length=1000)
    # honeypot: скрытое поле, человек его не заполняет
    website: str = ""


class PublicLeadAccepted(BaseModel):
    ok: bool = True
