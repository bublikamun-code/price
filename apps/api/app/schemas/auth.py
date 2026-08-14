"""DTO аутентификации. См. ARCHITECTURE_PLAN.md §6 (auth endpoints)."""
import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


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
        )
