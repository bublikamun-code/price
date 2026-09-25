"""API v2 session context with explicit organization memberships."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import EmailStr, Field

from app.models.enums import UserRole
from app.schemas.v2.common import CurrencyCode, V2Model


class CurrentUser(V2Model):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    display_currency: CurrencyCode
    consent_accepted: bool
    totp_enabled: bool
    price_digest_enabled: bool
    price_digest_sources: list[str] = Field(default_factory=list)
    force_password_change: bool = False
    phone: str | None = None
    legacy_company: str | None = None


class OrganizationMembership(V2Model):
    organization_id: uuid.UUID
    legal_name: str
    display_name: str | None
    role: str
    status: str
    is_primary: bool


class SessionContext(V2Model):
    user: CurrentUser
    commercial_scope: Literal["USER", "ORGANIZATION"] = "USER"
    organization_id: uuid.UUID | None = None
    memberships: list[OrganizationMembership] = Field(default_factory=list)


def current_user(user) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        display_currency=user.display_currency,
        consent_accepted=user.consent_accepted_at is not None,
        totp_enabled=user.totp_secret is not None,
        price_digest_enabled=user.price_digest_enabled,
        price_digest_sources=list(user.price_digest_sources or []),
        force_password_change=bool(getattr(user, "must_change_password", False)),
        phone=user.phone,
        legacy_company=user.company,
    )


def session_context(user, context=None) -> SessionContext:
    if context is None:
        return SessionContext(user=current_user(user))
    memberships = [
        OrganizationMembership(
            organization_id=item.organization_id,
            legal_name=item.legal_name,
            display_name=item.display_name,
            role=item.role,
            status=item.status,
            is_primary=item.is_primary,
        )
        for item in context.memberships
    ]
    return SessionContext(
        user=current_user(user),
        commercial_scope="ORGANIZATION" if context.organization_id else "USER",
        organization_id=context.organization_id,
        memberships=memberships,
    )


__all__ = ["CurrentUser", "SessionContext", "current_user", "session_context"]
