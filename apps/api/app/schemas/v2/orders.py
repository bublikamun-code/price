"""V2 order read projection with explicit organization ownership."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from app.models.enums import OrderStatus
from app.models.invoice import Invoice
from app.models.order import Order, OrderItem
from app.models.organization import Organization
from app.schemas.v2.cart import CartLine, CartSummary
from app.schemas.v2.common import (
    Money,
    Quantity,
    Rate,
    V2Model,
    money_amount,
    rate_value,
)
from app.schemas.v2.invoices import (
    InvoiceOut,
    InvoiceSummary,
    invoice_out,
    invoice_summary,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money(value: Decimal | float | str, currency: str) -> Money:
    return Money(amount=money_amount(value), currency=currency)


def _line_total(unit_price: Money, quantity: int) -> Money:
    return Money(
        amount=money_amount(Decimal(unit_price.amount) * quantity),
        currency=unit_price.currency,
    )


class OrderLine(V2Model):
    id: uuid.UUID
    product_id: uuid.UUID | None
    sku: str | None
    name: str | None
    quantity: int
    unit_price: Money
    line_total: Money
    note: str | None


class OrderItemCreate(V2Model):
    product_id: uuid.UUID
    quantity: Quantity
    note: str | None = Field(default=None, max_length=2000)


class OrderDeliveryCreate(V2Model):
    method: Literal["PICKUP", "DELIVERY"]
    address_id: uuid.UUID | None = None
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    preferred_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)


class OrderCreate(V2Model):
    draft_id: uuid.UUID | None = None
    items: list[OrderItemCreate] = Field(min_length=1, max_length=500)
    delivery: OrderDeliveryCreate

    @model_validator(mode="after")
    def _reject_duplicate_product_ids(self):
        seen: set[uuid.UUID] = set()
        for item in self.items:
            if item.product_id in seen:
                raise PydanticCustomError(
                    "duplicate_order_lines",
                    "Duplicate productId values are not allowed",
                )
            seen.add(item.product_id)
        return self


class DeliverySummary(V2Model):
    method: Literal["PICKUP", "DELIVERY"]
    pickup_point: str | None
    address_id: uuid.UUID | None = None
    address: str | None
    contact_name: str | None
    phone: str | None
    preferred_date: date | None
    comment: str | None


class OrderSummary(V2Model):
    """Lightweight order collection projection; never contains lines or media."""

    id: uuid.UUID
    sequence: int | None
    organization_id: uuid.UUID | None
    initiated_by_user_id: uuid.UUID
    status: OrderStatus
    total: Money
    exchange_rate: Rate
    # Счёт 1:1 с заказом (§16 п.40): в коллекции только {id, number, status} —
    # суммы и реквизиты покупателя там не выводятся.
    invoice: InvoiceSummary | None = None
    created_at: datetime
    updated_at: datetime
    version: int


class OrderDetail(V2Model):
    id: uuid.UUID
    sequence: int | None
    organization_id: uuid.UUID | None
    initiated_by_user_id: uuid.UUID
    manager_id: uuid.UUID | None
    status: OrderStatus
    total: Money
    exchange_rate: Rate
    lines: list[OrderLine]
    delivery: DeliverySummary
    # Полный блок счёта (номер, даты, сумма, статусы) — клиент видит кнопку
    # «Скачать счёт»; None, пока счёт не выставлен.
    invoice: InvoiceOut | None = None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    version: int


def _project_line(item: OrderItem) -> OrderLine:
    snapshot = item.product_snapshot or {}
    unit_price = _money(item.unit_price, item.currency_code)
    return OrderLine(
        id=item.id,
        product_id=item.product_id,
        sku=snapshot.get("sku"),
        name=snapshot.get("name"),
        quantity=item.quantity,
        unit_price=unit_price,
        line_total=_line_total(unit_price, item.quantity),
        note=item.note,
    )


def order_summary(order: Order, invoice: Invoice | None = None) -> OrderSummary:
    return OrderSummary(
        id=order.id,
        sequence=order.seq,
        organization_id=order.organization_id,
        initiated_by_user_id=order.client_id,
        status=order.status,
        total=_money(order.total_amount, order.currency_code),
        exchange_rate=Rate(
            value=rate_value(order.exchange_rate),
            source=order.rate_source or "LEGACY",
        ),
        invoice=invoice_summary(invoice) if invoice is not None else None,
        created_at=_utc(order.created_at),
        updated_at=_utc(order.updated_at),
        version=order.version,
    )


def order_detail(
    order: Order,
    items: list[OrderItem],
    *,
    invoice: Invoice | None = None,
    organization: Organization | None = None,
) -> OrderDetail:
    method = "DELIVERY" if order.delivery_method.lower() == "delivery" else "PICKUP"
    return OrderDetail(
        id=order.id,
        sequence=order.seq,
        organization_id=order.organization_id,
        initiated_by_user_id=order.client_id,
        manager_id=order.manager_id,
        status=order.status,
        total=_money(order.total_amount, order.currency_code),
        exchange_rate=Rate(
            value=rate_value(order.exchange_rate),
            source=order.rate_source or "LEGACY",
        ),
        lines=[_project_line(item) for item in items],
        delivery=DeliverySummary(
            method=method,
            pickup_point=order.delivery_point if method == "PICKUP" else None,
            address_id=order.delivery_address_id,
            address=order.delivery_address,
            contact_name=order.delivery_contact_name,
            phone=order.delivery_phone,
            preferred_date=order.delivery_preferred_date,
            comment=order.delivery_comment,
        ),
        invoice=invoice_out(invoice, organization=organization)
        if invoice is not None
        else None,
        notes=order.notes,
        created_at=_utc(order.created_at),
        updated_at=_utc(order.updated_at),
        version=order.version,
    )


__all__ = [
    "CartLine",
    "CartSummary",
    "DeliverySummary",
    "OrderCreate",
    "OrderDeliveryCreate",
    "OrderDetail",
    "OrderItemCreate",
    "OrderLine",
    "OrderSummary",
    "order_detail",
    "order_summary",
]
