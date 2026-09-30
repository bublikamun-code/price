"""Organization-scoped API v2 cart contract."""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import Field

from app.schemas.v2.common import Money, Quantity, Rate, V2Model, money_amount


class CartLineVolumeTier(V2Model):
    """Ступень скидки за объём, применённая к этой строке (§16 п.41).

    Порог сравнивается с ``quantity`` самой строки, а не с суммой по бренду:
    строки разных товаров одного бренда не образуют одну партию, а цена позиции
    должна воспроизводиться из её собственного количества.
    """

    min_qty: int
    discount_percent: float


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
    # Скидка за объём, применённая к строке; `None` — количество ниже первого
    # порога, лестницы у бренда нет, либо цена жёсткая из CSV (`override_price`,
    # §8 п.1 — объёмная скидка к ней не применяется).
    volume_tier: CartLineVolumeTier | None = None


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
    volume_tier: dict | None = None,
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
        volume_tier=(
            CartLineVolumeTier(
                min_qty=volume_tier["min_qty"],
                discount_percent=volume_tier["discount_percent"],
            )
            if volume_tier
            else None
        ),
    )


__all__ = [
    "CartItemAdd",
    "CartItemReplace",
    "CartLine",
    "CartLineVolumeTier",
    "CartSummary",
    "cart_line",
]
