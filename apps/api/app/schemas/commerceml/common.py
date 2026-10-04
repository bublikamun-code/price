"""Общие элементы CommerceML 2.x — JSON-адаптация (§18.1, §18.3).

CommerceML — де-факто стандарт обмена с 1С в СНГ. Мы готовим JSON-адаптацию
(не XML), имена полей — латиницей, версионирование — query-параметром
``?schema_version=`` (см. ``SCHEMA_VERSION``).

Связи с моделью БД:
  * ``product_id`` → ``products.external_1c_guid`` (§18.3);
  * ``order.external_id`` → ``orders.external_id`` (номер документа в 1С).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Версия схемы обмена (§18.1). Публикуется в каждом ответе 1С-эндпоинтов,
#: чтобы 1С могла отказаться от неподдерживаемой версии.
SCHEMA_VERSION: Final[str] = "2.10"


class CommerceMLModel(BaseModel):
    """Базовая модель документов CommerceML.

    ``populate_by_name`` — принимаем и snake_case (внутренний контракт), и
    alias'ы; ``str_strip_whitespace`` — данные 1С часто приходят с хвостовыми
    пробелами, резать их на границе удобнее, чем в каждом поле.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="ignore",  # 1С может присылать поля новее нашей схемы — не падаем
    )


class ProductIdentifier(CommerceMLModel):
    """``Идентификатор`` — ссылка на номенклатуру в 1С."""

    # ИдентификаторНоменклатуры — ключ связи с products.external_1c_guid.
    guid: str = Field(min_length=1, max_length=64, description="ИдентификаторНоменклатуры")
    sku: str = Field(default="", max_length=64, description="Артикул")
    name: str = Field(default="", max_length=512, description="Наименование")


class PriceValue(CommerceMLModel):
    """``ЦенаТовара`` — цена с валютой.

    Decimal, а не float: цена — деньги, накопление float-ошибок в прайсе
    недопустимо (§11).
    """

    price: Decimal = Field(ge=0, description="Цена за единицу")
    currency: str = Field(default="BYN", min_length=3, max_length=3, description="Валюта ISO-4217")
    quantity: Decimal = Field(default=Decimal(1), gt=0, description="Единица измерения/количество")


class Warehouse(CommerceMLModel):
    """``Склад`` — место хранения остатка."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=255)


class ExchangeStamp(CommerceMLModel):
    """Служебные штампы документа (дата документа + версия схемы)."""

    date: datetime = Field(description="Дата и время документа")
    schema_version: str = Field(default=SCHEMA_VERSION, description="Версия схемы CommerceML")