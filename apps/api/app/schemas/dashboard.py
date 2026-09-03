"""DTO клиентского дашборда (/api/v1/dashboard, экран /dashboard «Моя аналитика»).

См. ARCHITECTURE_PLAN.md §6, §16 п.20. Имена полей — строго под интерфейсы
фронта (apps/web/pages/dashboard.vue); деньги — Decimal (сериализуется в JSON
строкой), как в менеджерском дашборде.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ClientDashboardKPI(BaseModel):
    orders_total: int = Field(ge=0)
    orders_this_month: int = Field(ge=0)
    total_spent_byn: Decimal = Field(ge=0)
    avg_order_byn: Decimal = Field(ge=0)


class ClientOrdersByDayItem(BaseModel):
    date: date
    count: int = Field(ge=0)


class ClientStatusCount(BaseModel):
    status: str
    count: int = Field(ge=0)


class ClientTopProduct(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    qty: int
    revenue_byn: Decimal


class ClientRecentOrder(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: str
    total_amount: Decimal
    seq: int | None = None


class ClientActiveOrder(BaseModel):
    id: uuid.UUID
    number: str
    created_at: datetime
    status: str
    total_amount: Decimal


class ClientPriceChange(BaseModel):
    """Изменение цены товара из избранного между последними версиями прайса."""
    product_id: uuid.UUID
    sku: str
    name: str
    photo_key: str | None = None
    new_client_price: Decimal
    old_client_price: Decimal | None = None  # None — категория «new» (нет прошлой цены)
    currency: str
    category: Literal["down", "up", "new"]
    delta_percent: str | None = None         # «-12.50» / «5.00»; None для «new»


class ClientNewArrival(BaseModel):
    id: uuid.UUID
    sku: str
    name: str
    photo_key: str | None = None
    client_price: Decimal
    currency: str
    has_discount: bool


class ClientQuickActions(BaseModel):
    repeat_order_id: uuid.UUID | None = None  # последняя заявка клиента (любой статус)


class ClientDashboardOut(BaseModel):
    kpi: ClientDashboardKPI
    orders_by_day: list[ClientOrdersByDayItem]
    status_counts: list[ClientStatusCount]
    top_products: list[ClientTopProduct]
    recent_orders: list[ClientRecentOrder]
    active_orders: list[ClientActiveOrder]
    favorite_price_changes: list[ClientPriceChange]
    new_arrivals: list[ClientNewArrival]
    quick_actions: ClientQuickActions
