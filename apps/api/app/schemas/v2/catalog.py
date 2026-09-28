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
from app.schemas.v2.media import MediaResource

StockVisibility = Literal["IN_STOCK", "PREORDER"]


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
    # Плитка каталога: одно изображение (фото товара, иначе фото серии).
    # Галерея в detail-проекции — в `media`.
    thumbnail: MediaResource | None = None
    media: list[MediaResource] = Field(default_factory=list)


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
]
