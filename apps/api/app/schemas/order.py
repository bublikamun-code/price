"""DTO заявок (Этап 6). См. ARCHITECTURE_PLAN.md §9, §6."""
from datetime import date, datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderStatus
from app.schemas import MetaPage


class OrderItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, default=1)
    note: str | None = None


class DeliveryDetails(BaseModel):
    """Структурированные параметры получения заявки для нового web/iOS-контракта."""

    method: Literal["PICKUP", "DELIVERY"]
    pickup_point: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    preferred_date: date | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _location_required(self):
        if self.method == "PICKUP" and not self.pickup_point:
            raise ValueError("При самовывозе укажите pickup_point")
        if self.method == "DELIVERY" and not self.address:
            raise ValueError("При доставке укажите address")
        return self


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)
    notes: str | None = None
    price_calc_mode: Literal["fixed", "nbrb_current"] = "fixed"
    # Структурированный delivery block для v2-клиентов. Поля ниже оставлены
    # для обратной совместимости v1 и заполняются из delivery при наличии.
    delivery: DeliveryDetails | None = None
    # Способ получения: самовывоз (по умолчанию) или доставка.
    delivery_method: Literal["pickup", "delivery"] = "pickup"
    # Пункт самовывоза / комментарий доставки (не более 255 символов).
    delivery_point: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _point_required_for_pickup(self):
        if self.delivery is not None:
            return self
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
    organization_id: uuid.UUID | None = None
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
    delivery_address: str | None = None
    delivery_contact_name: str | None = None
    delivery_phone: str | None = None
    delivery_preferred_date: date | None = None
    delivery_comment: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead] | None = None
    # Сквозной номер заявки (для отображения «№N»).
    seq: int | None = None
    # Optimistic concurrency token для manager/admin writes.
    version: int = 1
    # Денормализованное имя/компания клиента (заполняется сервисом/роутером,
    # не хранится в orders — подтягивается из users при выдаче).
    client_name: str | None = None
    client_company: str | None = None


class OrderListPage(BaseModel):
    data: list[OrderRead]
    meta: MetaPage
