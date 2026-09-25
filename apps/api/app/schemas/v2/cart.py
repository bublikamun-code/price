"""Organization-scoped API v2 cart contract."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import Field

from app.schemas.v2.common import Money, Quantity, Rate, V2Model, money_amount


class CartLine(V2Model):
    product_id: uuid.UUID
    sku: str
    name: str
    brand_name: str | None
    stock_status: str
    quantity: int
    note: str | None
    unit_price: Money
    line_total: Money


class CartSummary(V2Model):
    """Current priced projection of one USER or ORGANIZATION cart."""

    id: uuid.UUID
    organization_id: uuid.UUID | None
    version: int = Field(ge=1)
    items: list[CartLine]
    total: Money
    total_items: int = Field(ge=0)
    exchange_rate: Rate


class CartItemAdd(V2Model):
    product_id: uuid.UUID
    quantity: Quantity
    note: str | None = Field(default=None, max_length=2000)


class CartItemReplace(V2Model):
    quantity: Quantity
    note: str | None = Field(default=None, max_length=2000)


def _line_total(unit_price: Money, quantity: int) -> Money:
    return Money(
        amount=money_amount(Decimal(unit_price.amount) * quantity),
        currency=unit_price.currency,
    )


def cart_line(
    *,
    product_id: uuid.UUID,
    sku: str,
    name: str,
    brand_name: str | None,
    stock_status: str,
    quantity: int,
    note: str | None,
    unit_price: Money,
) -> CartLine:
    return CartLine(
        product_id=product_id,
        sku=sku,
        name=name,
        brand_name=brand_name,
        stock_status=stock_status,
        quantity=quantity,
        note=note,
        unit_price=unit_price,
        line_total=_line_total(unit_price, quantity),
    )


__all__ = [
    "CartItemAdd",
    "CartItemReplace",
    "CartLine",
    "CartSummary",
    "cart_line",
]
