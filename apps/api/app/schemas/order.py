"""DTO заявок (Этап 6). См. ARCHITECTURE_PLAN.md §9, §6."""
from datetime import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus
from app.schemas import MetaPage


class OrderItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, default=1)
    note: str | None = None


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)
    notes: str | None = None
    price_calc_mode: Literal["fixed", "nbrb_current"] = "fixed"


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    manager_id: uuid.UUID | None = None


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID | None
    product_snapshot: dict
    quantity: int
    unit_price: float
    currency_code: str
    note: str | None


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    client_id: uuid.UUID
    manager_id: uuid.UUID | None
    status: OrderStatus
    currency_code: str
    exchange_rate: float
    rate_source: str | None
    total_amount: float
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead] | None = None


class OrderListPage(BaseModel):
    data: list[OrderRead]
    meta: MetaPage
