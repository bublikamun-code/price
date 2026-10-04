"""Документы CommerceML для складских остатков (§18.2 ``stock/import``)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.commerceml.common import (
    CommerceMLModel,
    ProductIdentifier,
    Warehouse,
)


class StockItem(CommerceMLModel):
    """``ОстатокТовара`` — остаток одной номенклатуры на складе."""

    product: ProductIdentifier
    warehouse: Warehouse
    quantity: Decimal = Field(ge=0, description="Доступно к отгрузке")
    reserved: Decimal = Field(default=Decimal(0), ge=0, description="Зарезервировано заказами")

    @property
    def available(self) -> Decimal:
        """Свободный остаток: доступно минус зарезервировано (не уходит в минус)."""
        return max(self.quantity - self.reserved, Decimal(0))


class StockDocument(CommerceMLModel):
    """``ОстаткиТоваров`` — срез остатков на момент времени."""

    date: datetime = Field(description="Момент снятия среза")
    items: list[StockItem] = Field(min_length=1, description="Позиции среза")