"""DTO заявок (Этап 6). См. ARCHITECTURE_PLAN.md §9, §6."""
from datetime import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    # Способ получения: самовывоз (по умолчанию) или доставка.
    delivery_method: Literal["pickup", "delivery"] = "pickup"
    # Пункт самовывоза / комментарий доставки (не более 255 символов).
    delivery_point: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _point_required_for_pickup(self):
        if self.delivery_method == "pickup" and not self.delivery_point:
            raise ValueError("При самовывозе укажите delivery_point (пункт выдачи)")
        return self


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
    # Способ получения и пункт самовывоза / пометка доставки.
    delivery_method: str = "pickup"
    delivery_point: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead] | None = None
    # Сквозной номер заявки (для отображения «№N»).
    seq: int | None = None
    # Денормализованное имя/компания клиента (заполняется сервисом/роутером,
    # не хранится в orders — подтягивается из users при выдаче).
    client_name: str | None = None
    client_company: str | None = None


class OrderListPage(BaseModel):
    data: list[OrderRead]
    meta: MetaPage
