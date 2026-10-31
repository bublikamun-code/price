"""API v2 organization and explicit membership projections.

These DTOs intentionally expose only commercial organization data. User
passwords, user pricing fields, and legacy company text are never projected.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.models.enums import ApprovalMode, OrganizationRole
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
    # Реквизиты для счёта на оплату (§16 п.40 п.4): печатаются в PDF,
    # правятся менеджером через PATCH /manager/organizations/{id}.
    bank_name: str | None = None
    bank_code: str | None = None
    bank_account: str | None = None
    # Согласование заявок (§16 п.42): режим визы OWNER и порог «сверх лимита».
    # Читают все участники организации; правит PATCH .../approval (OWNER/staff).
    approval_mode: ApprovalMode = ApprovalMode.OFF
    approval_limit_amount: Decimal | None = None


class OrganizationApprovalUpdate(V2Model):
    """Настройки визы (PATCH /organizations/{id}/approval, §16 п.42).

    При OVER_LIMIT лимит обязателен и строго положителен (422 иначе);
    при OFF/ALL допускается null — режим его не читает.
    """

    approval_mode: ApprovalMode
    approval_limit_amount: Decimal | None = None

    @model_validator(mode="after")
    def _over_limit_requires_positive_amount(self):
        if ApprovalMode(self.approval_mode) is ApprovalMode.OVER_LIMIT:
            if self.approval_limit_amount is None:
                raise ValueError(
                    "approvalLimitAmount обязателен при approvalMode=OVER_LIMIT"
                )
            if self.approval_limit_amount <= 0:
                raise ValueError(
                    "approvalLimitAmount должен быть положительным при OVER_LIMIT"
                )
        return self


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
    "OrganizationApprovalUpdate",
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
