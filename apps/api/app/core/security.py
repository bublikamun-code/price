"""Безопасность: хэширование паролей (bcrypt) + JWT (access/refresh).

См. ARCHITECTURE_PLAN.md §11, §16 п.15.
Алгоритм задаётся JWT_ALGORITHM: dev — HS256 (SECRET_KEY);
prod — RS256 (PEM-ключи из файлов, см. settings.jwt_signing_key/jwt_verify_key
и `make gen-jwt-keys`).
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


# ---------------- Пароли ----------------
def hash_password(plain: str) -> str:
    """bcrypt с salt=12 (§11). Возвращает строку."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Проверка пароля. False при любом несоответствии/невалидном хэше."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------- JWT ----------------
def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_delta,
        "type": token_type,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_signing_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.access_token_ttl_min),
        extra,
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject,
        "refresh",
        timedelta(days=settings.refresh_token_ttl_days),
    )


def create_2fa_ticket(subject: str) -> str:
    """Ticket второго шага логина при 2FA (§16 п.22).

    Короткоживущий JWT с type="2fa": только sub (без ролей/sid), TTL 5 мин.
    Не принимается get_current_user (ждёт type="access"), а verify-эндпоинт
    2FA не принимает access-токены — типы токенов строго разделены.
    """
    return _create_token(
        subject,
        "2fa",
        timedelta(minutes=settings.totp_ticket_ttl_min),
    )


def decode_token(token: str) -> dict[str, Any]:
    """Декодирует и проверяет срок. Бросает jwt.PyJWTError при невалидном токене."""
    return jwt.decode(token, settings.jwt_verify_key, algorithms=[settings.jwt_algorithm])


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "create_2fa_ticket",
    "decode_token",
]
