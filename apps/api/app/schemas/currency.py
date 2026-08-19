"""DTO курсов валют для менеджер-панели (§6, §17, §16 п.19)."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RateCurrency = Literal["USD", "EUR", "RUB"]


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    currency_code: str
    rate: Decimal
    scale: int
    fetched_at: date
    source: str
    is_manual: bool


class RatesOut(BaseModel):
    data: list[RateOut]


class ManualRateIn(BaseModel):
    currency_code: RateCurrency
    rate: Decimal = Field(gt=0)
    fetched_at: date | None = None
