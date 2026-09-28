"""API v2 organization and explicit membership projections.

These DTOs intentionally expose only commercial organization data. User
passwords, user pricing fields, and legacy company text are never projected.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

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


# Адресная книга доставки (Этап 2 дорожной карты). Модель OrganizationAddress
# хранит kind свободной строкой — на контрактной границе сужаем до трёх типов.
AddressKind = Literal["LEGAL", "DELIVERY", "PICKUP"]


class OrganizationAddressOut(V2Model):
    id: uuid.UUID
    kind: AddressKind
    label: str | None = None
    recipient_name: str | None = None
    phone: str | None = None
    address_line: str
    city: str | None = None
    postal_code: str | None = None
    country_code: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class OrganizationAddressCreate(V2Model):
    kind: AddressKind = "DELIVERY"
    label: str | None = Field(default=None, max_length=120)
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line: str = Field(min_length=1, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    country_code: str = Field(default="BY", min_length=2, max_length=2)
    is_default: bool = False


class OrganizationAddressPatch(V2Model):
    kind: AddressKind | None = None
    label: str | None = Field(default=None, max_length=120)
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    is_default: bool | None = None


# Descriptive aliases used by callers that prefer list/member terminology.
OrganizationListItem = OrganizationSummary
OrganizationMemberListItem = OrganizationMember
OrganizationMemberAdd = OrganizationMemberCreate

__all__ = [
    "OrganizationAddressCreate",
    "OrganizationAddressOut",
    "OrganizationAddressPatch",
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
