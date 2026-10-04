"""Документы CommerceML для прайса 1С → портал (§18.2 ``prices/import``).

Заменяет ручной импорт CSV: 1С присылает пакет цен одним документом.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.commerceml.common import (
    CommerceMLModel,
    ProductIdentifier,
)


class PriceItem(CommerceMLModel):
    """``ЦенаТовара`` — одна позиция прайса."""

    product: ProductIdentifier
    price: Decimal = Field(ge=0, description="Цена за единицу")
    currency: str = Field(default="BYN", min_length=3, max_length=3)
    min_quantity: Decimal = Field(default=Decimal(1), gt=0, description="Мин. количество для цены")
    effective_from: datetime | None = Field(
        default=None, description="Действует с; None = действует сейчас"
    )


class PriceDocument(CommerceMLModel):
    """``ПрайсЛист`` — документ прайса, приходящий из 1С."""

    date: datetime = Field(description="Дата и время формирования прайса")
    type: str = Field(
        default="retail", max_length=32, description="Тип прайса (retail / для клиентов 1С)"
    )
    items: list[PriceItem] = Field(min_length=1, description="Позиции прайса")