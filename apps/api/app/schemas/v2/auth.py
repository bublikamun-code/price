"""Native/Bearer session DTO for API v2 (ARCHITECTURE_PLAN.md §16 п.36).

Отдельная схема, а не переиспользование v1 `TokenPair`: там refresh помечен
`Field(exclude=True)` и уходит только в httpOnly-cookie, а нативному клиенту
нужен refresh в теле ответа — он хранит его в Keychain / EncryptedSharedPreferences
(docs/NATIVE_API_CONTRACT.md §4).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import EmailStr, Field

from app.schemas.v2.common import V2Model
from app.schemas.v2.session import CurrentUser
from app.models.user import Session as SessionModel

ClientType = Literal["WEB", "NATIVE"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SessionRequest(V2Model):
    """POST /api/v2/auth/sessions. `clientType=NATIVE` возвращает токены в теле."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    client_type: ClientType = "NATIVE"
    device_name: str | None = Field(default=None, max_length=128)
    os_name: str | None = Field(default=None, max_length=64, alias="os")
    app_version: str | None = Field(default=None, max_length=32)


class SessionRefreshRequest(V2Model):
    """POST /api/v2/auth/sessions/refresh. Refresh приходит в теле, не в cookie."""

    refresh_token: str = Field(min_length=1, max_length=512)


class TwoFaChallengeRequest(V2Model):
    """POST /api/v2/auth/2fa/challenges/verify.

    Метаданные устройства едут здесь же, а не отдельным объектом: сессия
    рождается именно на этом шаге, и клиенту не нужно слать их вторым запросом.
    """

    ticket: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=6, max_length=16)
    client_type: ClientType = "NATIVE"
    device_name: str | None = Field(default=None, max_length=128)
    os_name: str | None = Field(default=None, max_length=64, alias="os")
    app_version: str | None = Field(default=None, max_length=32)


class TwoFaChallenge(V2Model):
    """Ответ на login при включённой 2FA: токенов нет до verify."""

    two_fa_required: bool = True
    ticket: str
    force_password_change: bool = False


class SessionSummary(V2Model):
    id: str
    created_at: datetime
    expires_at: datetime
    device_name: str | None = None
    os_name: str | None = Field(default=None, alias="os")
    app_version: str | None = None
    client_type: str | None = None
    current: bool = False


class SessionGrant(V2Model):
    """Ответ на login/refresh: токены в теле + созданная сессия."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    force_password_change: bool = False
    session: SessionSummary
    user: CurrentUser


def session_summary(session: SessionModel, *, current: bool = False) -> SessionSummary:
    return SessionSummary(
        id=str(session.id),
        created_at=_utc(session.created_at),
        expires_at=_utc(session.expires_at),
        device_name=session.device_name,
        os_name=session.os_name,
        app_version=session.app_version,
        client_type=session.client_type,
        current=current,
    )


def session_grant(
    *,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    force_password_change: bool,
    session: SessionModel,
    user: CurrentUser,
) -> SessionGrant:
    now = datetime.now(timezone.utc)
    return SessionGrant(
        access_token=access_token,
        access_token_expires_at=now + timedelta(seconds=expires_in),
        refresh_token=refresh_token,
        refresh_token_expires_at=_utc(session.expires_at),
        force_password_change=force_password_change,
        session=session_summary(session, current=True),
        user=user,
    )


__all__ = [
    "ClientType",
    "SessionGrant",
    "SessionRefreshRequest",
    "SessionRequest",
    "SessionSummary",
    "TwoFaChallenge",
    "TwoFaChallengeRequest",
    "session_grant",
    "session_summary",
]
