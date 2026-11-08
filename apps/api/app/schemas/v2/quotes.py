"""Публичные схемы коммерческих предложений. Этап 8 роадмапа.

Money-поля — из ``schemas.v2.common``: суммы на публичной границе остаются
decimal string. Пагинация коллекций — CursorResponse (см. api/v2/quotes.py).
Цены КП — всегда BYN: менеджер задаёт override в национальной валюте,
пересчёт по курсу к КП не применяется (этап 8).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from app.models.enums import QuotePdfStatus, QuoteStatus
from app.models.quote import Quote, QuoteItem
from app.schemas.v2.common import Money, Quantity, V2Model, money_amount
from app.schemas.v2.orders import OrderDeliveryCreate


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


def _require_byn(money: Money) -> Money:
    """Цены КП — только BYN: EUR/USD-метка на override-цене ввела бы клиента
    в заблуждение (заморозка без пересчёта курса)."""
    if money.currency != "BYN":
        raise PydanticCustomError(
            "quote_currency_mismatch",
            "Quote item price must be in BYN",
        )
    return money


class QuoteItemOut(V2Model):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    unit_price: Money
    line_total: Money
    comment: str | None


class QuoteItemCreate(V2Model):
    product_id: uuid.UUID
    quantity: Quantity
    unit_price: Money
    comment: str | None = None

    @model_validator(mode="after")
    def _price_in_byn(self):
        _require_byn(self.unit_price)
        return self


class QuoteCreate(V2Model):
    """Тело ``POST /manager/quotes``: адресат + позиции + срок действия."""

    organization_id: uuid.UUID
    items: list[QuoteItemCreate] = Field(min_length=1, max_length=500)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _reject_duplicate_product_ids(self):
        seen: set[uuid.UUID] = set()
        for item in self.items:
            if item.product_id in seen:
                raise PydanticCustomError(
                    "duplicate_quote_lines",
                    "Duplicate productId values are not allowed",
                )
            seen.add(item.product_id)
        return self


class QuoteEdit(V2Model):
    """Тело ``PATCH /manager/quotes/{id}`` (DRAFT): None — «не трогать»."""

    items: list[QuoteItemCreate] | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_patch(self):
        if self.items is not None:
            if not (1 <= len(self.items) <= 500):
                raise PydanticCustomError(
                    "quote_items_length",
                    "Quote must contain between 1 and 500 items",
                )
            seen: set[uuid.UUID] = set()
            for item in self.items:
                if item.product_id in seen:
                    raise PydanticCustomError(
                        "duplicate_quote_lines",
                        "Duplicate productId values are not allowed",
                    )
                seen.add(item.product_id)
        return self


class QuoteAcceptCreate(V2Model):
    """Тело ``POST /quotes/{id}/accept`` — delivery как у создания заявки v2."""

    delivery: OrderDeliveryCreate


class QuoteSummary(V2Model):
    """Проекция коллекции: без позиций и PDF-файлов.

    ``number`` у DRAFT отсутствует (None) — номер присваивается при SEND.
    """

    id: uuid.UUID
    organization_id: uuid.UUID
    number: str | None
    status: QuoteStatus
    valid_until: datetime | None
    total: Money
    version: int
    created_at: datetime


class QuoteOut(V2Model):
    """Полная форма КП: позиции, суммы, статус PDF-рендера."""

    id: uuid.UUID
    organization_id: uuid.UUID
    number: str | None
    status: QuoteStatus
    valid_until: datetime | None
    seq: int | None
    total: Money
    pdf_status: QuotePdfStatus
    items: list[QuoteItemOut]
    version: int
    created_at: datetime
    updated_at: datetime


class QuoteStatusOut(V2Model):
    """Результат синхронного PDF-рендера (POST /manager/quotes/{id}/pdf)."""

    id: uuid.UUID
    pdf_status: QuotePdfStatus
    pdf_file_asset_id: uuid.UUID | None


def _project_item(item: QuoteItem) -> QuoteItemOut:
    unit_price = _money(item.unit_price, "BYN")
    return QuoteItemOut(
        id=item.id,
        product_id=item.product_id,
        sku=item.sku,
        name=item.name,
        quantity=int(item.qty),
        unit_price=unit_price,
        line_total=_line_total(unit_price, int(item.qty)),
        comment=item.comment,
    )


def quote_out(quote: Quote) -> QuoteOut:
    return QuoteOut(
        id=quote.id,
        organization_id=quote.organization_id,
        number=quote.number,
        status=quote.status,
        valid_until=_utc(quote.valid_until) if quote.valid_until else None,
        seq=quote.seq,
        total=_money(quote.total_amount, quote.currency_code),
        pdf_status=quote.pdf_status,
        items=[_project_item(item) for item in quote.items],
        version=quote.version,
        created_at=_utc(quote.created_at),
        updated_at=_utc(quote.updated_at),
    )


def quote_summary(quote: Quote) -> QuoteSummary:
    return QuoteSummary(
        id=quote.id,
        organization_id=quote.organization_id,
        number=quote.number,
        status=quote.status,
        valid_until=_utc(quote.valid_until) if quote.valid_until else None,
        total=_money(quote.total_amount, quote.currency_code),
        version=quote.version,
        created_at=_utc(quote.created_at),
    )


__all__ = [
    "QuoteAcceptCreate",
    "QuoteCreate",
    "QuoteEdit",
    "QuoteItemCreate",
    "QuoteItemOut",
    "QuoteOut",
    "QuoteStatusOut",
    "QuoteSummary",
    "quote_out",
    "quote_summary",
]
