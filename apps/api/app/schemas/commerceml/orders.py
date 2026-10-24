"""Документы CommerceML для заказов (§18.2 ``orders/export``, ``orders/status``).

Выгрузка заказов портал → 1С и возврат статуса заказа 1С → портал.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.schemas.commerceml.common import (
    CommerceMLModel,
    ExchangeStamp,
    ProductIdentifier,
)


class OrderCustomer(CommerceMLModel):
    """``Контрагент`` — покупатель в 1С.

    Держим ИНН/КПП и id клиента портала: связь по ИНН+КПП — штатный сценарий
    обмена, id портала — быстрый ключ при отладке.
    """

    id: str = Field(default="", max_length=64, description="id клиента в портале")
    inn: str = Field(default="", max_length=12, description="ИНН")
    kpp: str = Field(default="", max_length=12, description="КПП")
    name: str = Field(default="", max_length=512, description="Наименование")


class OrderLine(CommerceMLModel):
    """``ТоварЗаказа`` — позиция заказа."""

    product: ProductIdentifier
    quantity: Decimal = Field(gt=0, description="Количество")
    price: Decimal = Field(ge=0, description="Цена на единицу с учётом скидок")
    currency: str = Field(default="BYN", min_length=3, max_length=3)
    discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    note: str = Field(default="", max_length=512)


class OrderDocument(CommerceMLModel):
    """``ЗаказКлиента`` — заказ портала в терминах 1С.

    ``external_id`` — сквозной ключ обеих сторон (§18.3):
      * портал → 1С: номер документа 1С, если заказ уже выгружен;
      * 1С → портал: id заказа портала в ответе по статусу.
    """

    stamp: ExchangeStamp
    external_id: str = Field(min_length=1, max_length=64, description="Номер документа в 1С")
    portal_order_id: str = Field(default="", max_length=64, description="id заказа в портале")
    customer: OrderCustomer
    status: str = Field(default="new", max_length=32, description="Статус заказа")
    total: Decimal = Field(default=Decimal(0), ge=0)
    lines: list[OrderLine] = Field(min_length=1, description="Позиции заказа")

    @model_validator(mode="after")
    def _total_matches_lines(self) -> "OrderDocument":
        """Итог обязан сходиться с суммой позиций.

        Расхождение — признак рассинхрона цен между системами; молча пропускать
        его нельзя, документ не примут и в 1С, и в следующей выгрузке.
        """
        if not self.lines:
            return self
        computed = sum((line.price * line.quantity for line in self.lines), Decimal(0))
        if self.total != computed:
            raise ValueError(
                f"Итог заказа не сходится с позициями: total={self.total}, "
                f"сумма позиций={computed}"
            )
        return self


class OrderStatusChange(CommerceMLModel):
    """``СтатусЗаказа`` — возврат статуса заказа 1С → портал (§18.2)."""

    stamp: ExchangeStamp
    external_id: str = Field(min_length=1, max_length=64, description="Номер документа в 1С")
    status: str = Field(min_length=1, max_length=32, description="Новый статус в терминах 1С")
    changed_at: datetime = Field(description="Момент смены статуса в 1С")
    note: str = Field(default="", max_length=512)