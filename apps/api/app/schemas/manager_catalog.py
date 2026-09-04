"""DTO менеджер-панели: дашборд, товары, бренды/серии. См. §6, §16 п.20."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import StockStatus
from app.schemas import MetaPage
from app.schemas.dashboard import ClientNewArrival, ClientPromo


# --------------------------------------------------------- дашборд (фича G)
class DashboardKPI(BaseModel):
    orders_today: int = Field(ge=0)
    orders_7d: int = Field(ge=0)
    revenue_month: Decimal = Field(ge=0)
    new_clients_7d: int = Field(ge=0)
    active_imports: int = Field(ge=0)


class OrdersByDayItem(BaseModel):
    date: date
    count: int = Field(ge=0)


class TopProductItem(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    qty: int
    revenue: Decimal


class TopClientItem(BaseModel):
    client_id: uuid.UUID
    name: str
    orders: int
    revenue: Decimal


class RecentOrderItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    client_name: str
    status: str
    total_amount: Decimal


class DashboardOut(BaseModel):
    kpi: DashboardKPI
    orders_by_day: list[OrdersByDayItem]
    top_products: list[TopProductItem]
    top_clients: list[TopClientItem]
    recent_orders: list[RecentOrderItem]
    # Акции/новинки: тот же шейп, что клиентский дашборд (§16 п.20-1). У менеджера
    # в client_price — розничная цена BYN (персональной скидки нет).
    new_arrivals: list[ClientNewArrival] = []
    promos: list[ClientPromo] = []


# ------------------------------------------------------------- товары (п.20-2)
class ManagerBrandRef(BaseModel):
    id: uuid.UUID
    name: str


class ManagerSeriesRef(BaseModel):
    id: uuid.UUID
    name: str


class ManagerProductRead(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    brand: ManagerBrandRef | None = None
    series: ManagerSeriesRef | None = None
    base_price: Decimal
    override_price: Decimal | None = None
    stock_status: StockStatus
    # Остаток на складе, шт (None — не заведён). Клиентские/catalog-схемы это поле не отдают.
    stock_qty: int | None = None


class ManagerProductPage(BaseModel):
    data: list[ManagerProductRead]
    meta: MetaPage


class ManagerProductPatchIn(BaseModel):
    """Патч товара: override_price (null — сброс), stock_status и/или stock_qty."""

    override_price: Decimal | None = Field(default=None, ge=0)
    stock_status: StockStatus | None = None
    stock_qty: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one(self):
        # Проверяем именно факт передачи поля (model_fields_set), а не значение:
        # {"override_price": null} — валидный запрос на сброс ручной цены.
        if not self.model_fields_set & {"override_price", "stock_status", "stock_qty"}:
            raise ValueError("Укажите override_price, stock_status или stock_qty")
        return self


# --------------------------------------------------------- бренды/серии (п.20-3)
class BrandOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    series_count: int = Field(ge=0)
    products_count: int = Field(ge=0)


class BrandCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class BrandRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class SeriesPhotoOut(BaseModel):
    photo_key: str
    photo_url: str


class ProductPhotoOut(BaseModel):
    """Ответ на загрузку доп. фото товара (201, §6): только ключ нового фото."""
    photo_key: str
