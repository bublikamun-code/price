"""DTO аутентификации. См. ARCHITECTURE_PLAN.md §6 (auth endpoints), §20.4 (дайджест цен),
§16 п.22 (2FA фича H + журнал сессий фича I).
"""
import re
import uuid
from datetime import datetime
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
    # Принудительная смена временного пароля (§16 п.19): true → фронт ведёт
    # на /force-change-password.
    force_password_change: bool = False


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
    # 2FA менеджера (фича H, §16 п.22) — для экрана /profile/security
    totp_enabled: bool
    # Дайджест изменения цен (§20.4)
    price_digest_enabled: bool
    price_digest_sources: list[str]
    # Принудительная смена временного пароля (§16 п.19, /force-change-password)
    force_password_change: bool = False

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
            totp_enabled=user.totp_secret is not None,
            price_digest_enabled=user.price_digest_enabled,
            price_digest_sources=list(user.price_digest_sources or []),
            force_password_change=bool(getattr(user, "must_change_password", False)),
        )


class UserUpdate(BaseModel):
    """PATCH /auth/me: частичное обновление профиля (§6).

    Все поля Optional, но хотя бы одно должно быть задано — иначе 422 «нечего обновлять».
    Дубликаты price_digest_sources дедуплицируются (порядок сохраняется): источники —
    множество, повтор в запросе ошибки не означает.

    consent_accepted (§16 п.20-6): True — принять согласие (идемпотентно, фиксируется
    в consent_log); False — отзыв, запрещён через API (422 в сервисе).
    """
    display_currency: str | None = None
    price_digest_enabled: bool | None = None
    price_digest_sources: list[Literal["cart", "favorite", "orders"]] | None = None
    consent_accepted: bool | None = None

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
            and self.consent_accepted is None
        ):
            raise ValueError("Нечего обновлять: укажите хотя бы одно поле")
        return self


# =========================================================
# 2FA (фича H, §16 п.22)
# =========================================================
class TwoFASetupOut(BaseModel):
    """Сгенерированный на лету TOTP-секрет. НЕ сохраняется до POST /2fa/enable."""

    secret: str
    otpauth_uri: str
    qr_png_data_url: str


class TwoFASetupResponse(BaseModel):
    """Envelope §6: ``{"data": {secret, otpauth_uri, qr_png_data_url}}``."""

    data: TwoFASetupOut


class TwoFAEnableRequest(BaseModel):
    """Включение 2FA: секрет из setup + текущий TOTP-код для подтверждения."""

    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=10)


class TwoFAEnableOut(BaseModel):
    """Recovery-коды в plaintext — показываются ровно 1 раз (паттерн §16 п.19)."""

    recovery_codes: list[str]


class TwoFAEnableResponse(BaseModel):
    """Envelope §6: ``{"data": {"recovery_codes": [...]}}``."""

    data: TwoFAEnableOut


class TwoFAVerifyRequest(BaseModel):
    """Второй шаг логина: ticket из login + TOTP-код или recovery-код."""

    ticket: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=10)


class TelegramAuthRequest(BaseModel):
    """Mini App auth (§16 п.27): подписанные initData (+код связки при первом входе)."""

    init_data: str = Field(min_length=1)
    link_code: str | None = Field(default=None, min_length=6, max_length=6)


class MiniAppAuthOut(TokenPair):
    """Ответ m-auth: токены (куки ставит роутер) + факт связки + пользователь."""

    linked: bool = False
    user: "UserPublic"


class TelegramLinkCodeOut(BaseModel):
    """Одноразовый код связки Telegram из веб-кабинета (§16 п.27)."""

    code: str
    expires_in: int


class TwoFALoginRequired(BaseModel):
    """Ответ login при включённой 2FA: без токенов и кук (§16 п.22)."""

    two_fa_required: bool = True
    ticket: str


class TwoFADisableRequest(BaseModel):
    """Отключение 2FA: подтвердить TOTP/recovery-кодом ИЛИ паролём.

    Хотя бы одно поле обязательно; оба можно — проверяется по очереди.
    """

    code: str | None = Field(default=None, min_length=6, max_length=10)
    password: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.code is None and self.password is None:
            raise ValueError("Укажите code или password")
        return self


# =========================================================
# Журнал сессий (фича I, §16 п.22)
# =========================================================
class SessionOut(BaseModel):
    """Активная сессия пользователя. ``current`` — сессия текущей refresh-куки."""

    id: uuid.UUID
    user_agent: str | None = None
    ip: str | None = None
    created_at: datetime
    expires_at: datetime
    current: bool


class SessionListResponse(BaseModel):
    """Envelope §6 списка активных сессий (без пагинации — их немного)."""

    data: list[SessionOut]


class ForgotPasswordRequest(BaseModel):
    """Запрос сброса пароля. Ответ всегда 202 — существование аккаунта не раскрываем."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Сброс пароля по токену из письма. Новый пароль — минимум 8 символов."""

    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password: смена текущего (временного) пароля залогиненным.

    current_password проверяется сервисом (bcrypt); новый пароль — минимум
    8 символов (аудит 2026-09-06: ранее set/reset принимали пароль от 1 символа).
    """

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
