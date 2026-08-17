"""DTO каталога. См. ARCHITECTURE_PLAN.md §6."""
import uuid
from typing import Literal

from pydantic import BaseModel

from app.models.enums import StockStatus
from app.schemas import MetaPage


class BrandRef(BaseModel):
    id: uuid.UUID
    name: str


class SeriesRef(BaseModel):
    id: uuid.UUID
    name: str
    brand_id: uuid.UUID | None = None
    photo_key: str | None = None


class ProductCard(BaseModel):
    """Карточка товара с ценами под текущего клиента."""
    id: uuid.UUID
    sku: str
    name: str
    brand: BrandRef | None = None
    series: SeriesRef | None = None
    stock_status: StockStatus
    photo_key: str | None = None
    attributes: dict = {}  # характеристики товара (§5): цвет, модули, IP-рейтинг…

    # Цены
    base_price_byn: float          # базовая (розница) в BYN
    retail_price: float            # розница в display-валюте
    client_price: float            # цена клиента (со скидкой) в display-валюте
    currency: str                  # display-валюта
    rate_source: str               # BYN | FIXED | NBRB
    has_discount: bool


class ProductDetail(ProductCard):
    """Детальная карточка (соседи по серии добавляются отдельно)."""
    override_price: float | None = None


class PriceHistoryItem(BaseModel):
    base_price: float
    override_price: float | None = None
    changed_at: str  # ISO datetime


class CatalogPage(BaseModel):
    data: list[ProductCard]
    meta: MetaPage


class FiltersOut(BaseModel):
    brands: list[BrandRef]
    series: list[SeriesRef]
    stock: list[str]


class ExportStartOut(BaseModel):
    """Ответ на запуск экспорта каталога (202, §16 п.16)."""
    job_id: str


class ExportJobOut(BaseModel):
    """Статус job экспорта каталога. ``url`` (presigned, 5 мин) — только при DONE."""
    job_id: str
    status: Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
    format: str
    error: str | None = None
    url: str | None = None
