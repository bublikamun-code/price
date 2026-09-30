"""Read-only API v2 catalog projections.

Prices are resolved by the existing pricing service and exposed as Money/Rate
objects. Media is exposed as stable media resources (§16 п.37) — internal S3
keys never enter this transport.
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.schemas.v2.common import Money, Rate, V2Model
from app.schemas.v2.documents import ProductDocument
from app.schemas.v2.media import MediaResource

StockVisibility = Literal["IN_STOCK", "PREORDER"]


class VolumeTierHint(V2Model):
    """Одна ступень лестницы за объём в том виде, в каком она уходит в UI."""

    min_qty: int
    discount_percent: float


class BrandRef(V2Model):
    id: uuid.UUID
    name: str


class SeriesRef(V2Model):
    id: uuid.UUID
    name: str
    brand_id: uuid.UUID


class CatalogProduct(V2Model):
    id: uuid.UUID
    sku: str
    name: str
    brand: BrandRef | None = None
    series: SeriesRef | None = None
    stock_status: StockVisibility
    stock_quantity: int | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    base_price: Money
    retail_price: Money
    client_price: Money
    exchange_rate: Rate
    has_discount: bool
    # Лестница скидок за объём бренда (§16 п.41). В каталоге количество
    # неизвестно, поэтому `clientPrice` объёмную скидку не учитывает, а товар
    # публикует всю лестницу — по ней UI рисует «от 10 шт −2%». Объёмная цена
    # считается в корзине, где `quantity` уже известен (§8).
    volume_tiers: list[VolumeTierHint] = Field(default_factory=list)
    # Плитка каталога: одно изображение (фото товара, иначе фото серии).
    # Галарея в detail-проекции — в `media`.
    thumbnail: MediaResource | None = None
    media: list[MediaResource] = Field(default_factory=list)
    # Документы товара (§16 п.38): заполняется только в detail-проекции
    # (свои + документы серии товара, со scope и is_expired).
    documents: list[ProductDocument] = Field(default_factory=list)



class CatalogFacets(V2Model):
    brands: list[BrandRef] = Field(default_factory=list)
    series: list[SeriesRef] = Field(default_factory=list)
    stock_statuses: list[StockVisibility] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


__all__ = [
    "BrandRef",
    "CatalogFacets",
    "CatalogProduct",
    "SeriesRef",
    "StockVisibility",
    "VolumeTierHint",
    # Реэкспорт для удобства потребителей карточки (роутеры, фикстуры).
    "ProductDocument",
]
