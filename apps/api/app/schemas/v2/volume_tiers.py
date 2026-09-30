"""Контракт скидок за объём в API v2 (§16 п.41).

Наружу — camelCase (§6 «Базовые правила v2»): ``minQty``, ``discountPercent``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.models.catalog import BrandVolumeTier
from app.schemas.v2.common import V2Model


class VolumeTierOut(V2Model):
    id: uuid.UUID
    brand_id: uuid.UUID
    min_qty: int
    # Процент уходит числом, а не строкой, как деньги: в БД это NUMERIC(5,2),
    # но `2.00` в JSON-строке заставила бы клиента разбирать одно и то же поле
    # двумя типами в зависимости от эндпоинта (тут строка, в VolumeTierHint и
    # CartLineVolumeTier — число). Точность до сотых гарантирует NUMERIC(5,2).
    discount_percent: float
    version: int
    created_at: datetime
    updated_at: datetime


class VolumeTierCreateIn(V2Model):
    """Тело POST. Границы (min_qty >= 1, 0 < d < 100) проверяет сервис: на
    клиенте они обходятся прямым вызовом API."""

    min_qty: int = Field(alias="minQty", ge=1)
    discount_percent: Decimal = Field(alias="discountPercent", gt=0, lt=100)


class VolumeTierUpdateIn(V2Model):
    """Тело PATCH: хотя бы одно поле; отсутствующее не меняется."""

    min_qty: int | None = Field(default=None, alias="minQty", ge=1)
    discount_percent: Decimal | None = Field(
        default=None, alias="discountPercent", gt=0, lt=100
    )


def volume_tier_out(tier: BrandVolumeTier) -> VolumeTierOut:
    return VolumeTierOut(
        id=tier.id,
        brand_id=tier.brand_id,
        min_qty=tier.min_qty,
        discount_percent=float(tier.discount_percent),
        version=tier.version,
        created_at=tier.created_at,
        updated_at=tier.updated_at,
    )


__all__ = [
    "VolumeTierCreateIn",
    "VolumeTierOut",
    "VolumeTierUpdateIn",
    "volume_tier_out",
]
