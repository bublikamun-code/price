"""Общие примитивы публичного API v2.

Модуль намеренно не зависит от v1 DTO: v1 сохраняет float/legacy envelope,
а v2 формирует собственный cross-client контракт для web и будущих iOS.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Generic, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

T = TypeVar("T")

# Текущие валюты проекта. Валидатор не принимает произвольные три буквы,
# чтобы ошибочный display_currency не попал в v2 money snapshot.
SUPPORTED_CURRENCIES = frozenset({"BYN", "EUR", "RUB", "USD"})
CurrencyCode = Annotated[
    str,
    StringConstraints(min_length=3, max_length=3, to_upper=True),
    AfterValidator(lambda value: value if value in SUPPORTED_CURRENCIES else _invalid_currency(value)),
]

# Все валюты текущего commercial scope имеют два decimal places.
MONEY_SCALE = 2
RATE_SCALE = 4
MAX_DATABASE_INTEGER = 2_147_483_647


def _invalid_currency(value: str) -> str:
    raise ValueError(f"Unsupported ISO 4217 currency: {value}")


def _to_decimal(value: Decimal | float | str) -> Decimal:
    try:
        # str() исключает двоичный артефакт repr(float), например 0.1.
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Amount must be a decimal value") from exc


def money_amount(value: Decimal | float | str) -> str:
    """Фиксированная денежная строка с округлением HALF_UP до 2 знаков."""
    amount = _to_decimal(value).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return format(amount, ".2f")


def rate_value(value: Decimal | float | str) -> str:
    """Фиксированная десятичная строка курса с четырьмя знаками."""
    amount = _to_decimal(value).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return format(amount, ".4f")


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def validate_positive_quantity(value: str) -> str:
    """Validate the canonical decimal-string form used by PostgreSQL INTEGER."""
    normalized = str(int(value))
    if normalized != value:
        raise ValueError("Quantity must be a canonical positive decimal integer string")
    if int(value) > MAX_DATABASE_INTEGER:
        raise ValueError("Quantity exceeds the database integer range")
    return normalized


Quantity = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=False,
        pattern=r"^[1-9]\d*$",
        min_length=1,
        max_length=10,
    ),
    AfterValidator(validate_positive_quantity),
]


class V2Model(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )


class Money(V2Model):
    amount: str = Field(
        examples=["1234.56"],
        description="Decimal amount serialized as a JSON string with two places.",
    )
    currency: CurrencyCode = Field(examples=["BYN"])

    @field_validator("amount")
    @classmethod
    def _validate_amount(cls, value: str) -> str:
        return money_amount(value)

    @classmethod
    def from_value(cls, value: Decimal | float | str, *, currency: str) -> Money:
        return cls(amount=money_amount(value), currency=currency)


class Rate(V2Model):
    value: str = Field(pattern=r"^-?\d+\.\d{4}$", examples=["3.0000"])
    scale: int = Field(default=RATE_SCALE, ge=0, le=8)
    source: str = Field(min_length=1, max_length=64)


class ResponseMeta(V2Model):
    request_id: str = Field(min_length=1, examples=["0198f0d2-58f2-79a7-8123-2c72c1548f90"])


class SuccessResponse(V2Model, Generic[T]):
    data: T
    meta: ResponseMeta


class CursorMeta(ResponseMeta):
    next_cursor: str | None = None
    has_more: bool = False
    # Потолок совпадает с le=100 на query-параметре limit всех v2-списков:
    # раньше схема разрешала 200, и DTO мог пройти валидацию со значением,
    # которое эндпоинт отверг бы.
    limit: int = Field(ge=1, le=100)
    sort: str = Field(min_length=1, max_length=32)


class CursorResponse(V2Model, Generic[T]):
    data: list[T]
    meta: CursorMeta


class ProblemFieldError(V2Model):
    field: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProblemDetails(V2Model):
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: int = Field(ge=400, le=599)
    detail: str = Field(min_length=1)
    instance: str = Field(min_length=1)
    code: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    errors: list[ProblemFieldError] = Field(default_factory=list)


def decimal_from_money(money: Money) -> Decimal:
    """Internal helper for line totals; never used as a public JSON payload."""
    return Decimal(money.amount)


__all__ = [
    "MAX_DATABASE_INTEGER",
    "RATE_SCALE",
    "SUPPORTED_CURRENCIES",
    "CurrencyCode",
    "CursorMeta",
    "CursorResponse",
    "Money",
    "ProblemDetails",
    "ProblemFieldError",
    "Quantity",
    "Rate",
    "ResponseMeta",
    "SuccessResponse",
    "V2Model",
    "decimal_from_money",
    "money_amount",
    "rate_value",
    "to_camel",
]
