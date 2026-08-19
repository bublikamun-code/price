"""DTO клиентов менеджер-панели (§6, §16 п.19)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas import MetaPage
from app.schemas.currency import RateOut

MANAGER_DISPLAY_CURRENCIES = Literal["BYN", "USD", "EUR", "RUB"]
FIXABLE_CURRENCIES = Literal["USD", "EUR", "RUB"]


class UserManagerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    company: str | None
    phone: str | None
    role: str
    is_active: bool
    display_currency: str
    price_digest_enabled: bool
    price_digest_sources: list[str]
    consent_accepted_at: datetime | None
    created_at: datetime
    fixed_rate: RateOut | None = None

    @classmethod
    def from_user(cls, user, fixed_rate=None) -> "UserManagerRead":
        """fixed_rate загружается отдельным запросом (у User нет relationship)."""
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            company=user.company,
            phone=user.phone,
            role=user.role.value if hasattr(user.role, "value") else user.role,
            is_active=user.is_active,
            display_currency=user.display_currency,
            price_digest_enabled=user.price_digest_enabled,
            price_digest_sources=list(user.price_digest_sources or []),
            consent_accepted_at=user.consent_accepted_at,
            created_at=user.created_at,
            fixed_rate=fixed_rate,
        )


class UserManagerListItem(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    company: str | None
    phone: str | None
    is_active: bool
    display_currency: str
    created_at: datetime
    fixed_rate_currency: str | None
    avg_discount_percent: Decimal | None
    orders_count: int


class UserManagerPage(BaseModel):
    data: list[UserManagerListItem]
    meta: MetaPage


class ClientCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    company: str | None = None
    phone: str | None = None
    discount_percent_all: Decimal | None = Field(default=None, ge=0, le=100)


class ClientCreateOut(BaseModel):
    user: UserManagerRead
    temp_password: str


class UserPatchIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    company: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    display_currency: MANAGER_DISPLAY_CURRENCIES | None = None


class TempPasswordOut(BaseModel):
    temp_password: str


class DiscountIn(BaseModel):
    brand_id: uuid.UUID
    percent: Decimal = Field(ge=0, le=100)


class DiscountsIn(BaseModel):
    discounts: list[DiscountIn] = Field(max_length=500)


class DiscountOut(BaseModel):
    brand_id: uuid.UUID
    brand_name: str
    percent: Decimal


class UserManagerDetail(BaseModel):
    user: UserManagerRead
    discounts: list[DiscountOut]


class FixedRateIn(BaseModel):
    reset: bool = False
    currency_code: FIXABLE_CURRENCIES | None = None
    rate: Decimal | None = Field(default=None, gt=0)
