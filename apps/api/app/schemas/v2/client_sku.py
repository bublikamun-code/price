"""Контракт кросс-справочника клиентских артикулов в API v2 (§16 п.43).

Наружу — camelCase (§6 «Базовые правила v2»): ``clientSku``, ``productId``,
``cartVersion``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.v2.common import Money, ResponseMeta, V2Model

# Артикул клиента: trim на транспортной границе (Excel-вставки любят хвостовые
# пробелы), 1..64 символа после trim. CITEXT в БД сравнивает без регистра.
ClientSkuStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class ClientSkuMappingOut(V2Model):
    id: uuid.UUID
    organization_id: uuid.UUID
    client_sku: str
    product_id: uuid.UUID
    note: str | None = None
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class ClientSkuMappingCreate(V2Model):
    """Тело POST: связка «артикул клиента → наш SKU»."""

    client_sku: ClientSkuStr
    product_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class ClientSkuMappingUpdate(V2Model):
    """Тело PATCH: перемапить товар и/или править заметку; absent не меняется."""

    product_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class ClientSkuApplyCsvIn(V2Model):
    """Тело apply-csv: сырой текст вставки (≤ 256 КиБ)."""

    csv: str = Field(min_length=1, max_length=262144)


class ClientSkuApplyRow(V2Model):
    """Отчёт по одной строке файла (частичный успех, §16 п.43 п.3/4)."""

    client_sku: str
    qty: int
    status: Literal["MATCHED", "UNKNOWN", "AMBIGUOUS"]
    # Resolved product UUID обязателен для MATCHED (урок из API_V2_CONTRACT
    # §10); null у UNKNOWN/AMBIGUOUS.
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    product_sku: str | None = None
    # Клиентская цена строки (батч-прайсинг, как в resolve-bulk) и складской
    # статус; у UNKNOWN/AMBIGUOUS — null.
    unit_price: Money | None = None
    stock_status: str | None = None
    message: str | None = None


class ClientSkuApplySummary(V2Model):
    matched: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)
    ambiguous: int = Field(default=0, ge=0)
    cart_added: int = Field(default=0, ge=0)


class ClientSkuApplyOut(V2Model):
    rows: list[ClientSkuApplyRow]
    summary: ClientSkuApplySummary
    # Версия корзины после последней мутации (значение ETag корзины); None,
    # если ни одна строка не попала в корзину. Фронт после apply обновляет
    # корзину forceRefresh'ем.
    cart_version: str | None = None


class PageMeta(ResponseMeta):
    """Offset-пагинация списков справочника (page/pageSize, default 20)."""

    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


__all__ = [
    "ClientSkuApplyCsvIn",
    "ClientSkuApplyOut",
    "ClientSkuApplyRow",
    "ClientSkuApplySummary",
    "ClientSkuMappingCreate",
    "ClientSkuMappingOut",
    "ClientSkuMappingUpdate",
    "PageMeta",
]
