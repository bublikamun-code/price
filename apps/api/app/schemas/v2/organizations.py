"""API v2 organization and explicit membership projections.

These DTOs intentionally expose only commercial organization data. User
passwords, user pricing fields, and legacy company text are never projected.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import OrganizationRole
from app.schemas.v2.common import V2Model


class OrganizationSummary(V2Model):
    id: uuid.UUID
    legal_name: str
    display_name: str | None = None
    tax_id: str | None = None
    country_code: str
    default_currency: str
    is_active: bool
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class OrganizationDetail(OrganizationSummary):
    legal_address: str | None = None
    legal_email: str | None = None
    legal_phone: str | None = None


class OrganizationMember(V2Model):
    organization_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    phone: str | None = None
    role: OrganizationRole
    is_active: bool
    is_primary: bool
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class OrganizationMemberCreate(V2Model):
    user_id: uuid.UUID
    role: OrganizationRole = OrganizationRole.BUYER
    is_active: bool = True
    is_primary: bool = False


class OrganizationMemberPatch(V2Model):
    role: OrganizationRole | None = None
    is_active: bool | None = None
    is_primary: bool | None = None
    # The transport concurrency token is If-Match. Accepting an optional body
    # value keeps the DTO forward-compatible without replacing the header.
    version: int | None = Field(default=None, ge=1)


class OrganizationSelectionRequest(V2Model):
    organization_id: uuid.UUID | None = None


# Descriptive aliases used by callers that prefer list/member terminology.
OrganizationListItem = OrganizationSummary
OrganizationMemberListItem = OrganizationMember
OrganizationMemberAdd = OrganizationMemberCreate

__all__ = [
    "OrganizationDetail",
    "OrganizationListItem",
    "OrganizationMember",
    "OrganizationMemberAdd",
    "OrganizationMemberCreate",
    "OrganizationMemberListItem",
    "OrganizationMemberPatch",
    "OrganizationSelectionRequest",
    "OrganizationSummary",
]
