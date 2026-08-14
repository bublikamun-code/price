"""DTO аутентификации. См. ARCHITECTURE_PLAN.md §6 (auth endpoints), §20.4 (дайджест цен)."""
import re
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import UserRole

# display_currency: ровно 3 латинские заглавные буквы. Та же проверка, что добавлена
# аудитом безопасности для base_currency в app/api/v1/manager/prices.py ([A-Z]{3}):
# сначала нормализация (strip + upper), затем строгий fullmatch.
_CURRENCY_RE = re.compile(r"[A-Z]{3}")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    """Внутренняя пара токенов; refresh исключается из HTTP-ответа роутером."""
    access_token: str
    refresh_token: str = Field(exclude=True)
    token_type: str = "bearer"
    expires_in: int = Field(description="Срок жизни access-токена, сек.")


class UserPublic(BaseModel):
    """Публичное представление пользователя (без password_hash, totp_secret)."""
    id: uuid.UUID
    email: EmailStr
    full_name: str
    company: str | None = None
    phone: str | None = None
    role: UserRole
    is_active: bool
    display_currency: str
    consent_accepted: bool
    # Дайджест изменения цен (§20.4)
    price_digest_enabled: bool
    price_digest_sources: list[str]

    @classmethod
    def from_user(cls, user) -> "UserPublic":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            company=user.company,
            phone=user.phone,
            role=user.role,
            is_active=user.is_active,
            display_currency=user.display_currency,
            consent_accepted=user.consent_accepted_at is not None,
            price_digest_enabled=user.price_digest_enabled,
            price_digest_sources=list(user.price_digest_sources or []),
        )


class UserUpdate(BaseModel):
    """PATCH /auth/me: частичное обновление профиля (§6).

    Все поля Optional, но хотя бы одно должно быть задано — иначе 422 «нечего обновлять».
    Дубликаты price_digest_sources дедуплицируются (порядок сохраняется): источники —
    множество, повтор в запросе ошибки не означает.
    """
    display_currency: str | None = None
    price_digest_enabled: bool | None = None
    price_digest_sources: list[Literal["cart", "favorite", "orders"]] | None = None

    @field_validator("display_currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        # Нормализация + проверка как для base_currency в manager/prices.py
        if value is None:
            return None
        currency = value.strip().upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("display_currency должна состоять ровно из 3 латинских букв")
        return currency

    @field_validator("price_digest_sources")
    @classmethod
    def _dedup_sources(cls, value: list[str] | None) -> list[str] | None:
        # dict.fromkeys сохраняет порядок первого вхождения
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _at_least_one(self):
        if (
            self.display_currency is None
            and self.price_digest_enabled is None
            and self.price_digest_sources is None
        ):
            raise ValueError("Нечего обновлять: укажите хотя бы одно поле")
        return self
