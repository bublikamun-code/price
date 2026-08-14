"""DTO избранного клиента (Этап 6). См. ARCHITECTURE_PLAN.md §6."""
import uuid

from pydantic import BaseModel, Field

from app.schemas import MetaPage


class FavoriteCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)


class FavoriteRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    brand_name: str | None
    photo_key: str | None
    stock_status: str
    base_price_byn: float
    retail_price: float
    client_price: float
    currency: str
    has_discount: bool


class FavoriteListPage(BaseModel):
    data: list[FavoriteRead]
    meta: MetaPage
