"""Organization-aware B2B entities.

The schema is intentionally expand-only.  ``User.company`` and user-level
pricing remain untouched while real memberships are introduced explicitly by a
manager or a future organization import flow.
"""
import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import OrganizationRole, pg_enum


class Organization(Base, UUIDPrimaryKey, TimestampMixin):
    """A separately verified commercial organization."""

    __tablename__ = "organizations"

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="BY", nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    # Canonical organization details; delivery addresses live in the table below.
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    legal_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Банковские реквизиты покупателя для счёта на оплату (§16 п.40 п.4).
    # Nullable: расчётного счёта в связке с нами может не быть, пустое поле
    # печатается в PDF прочерком. Дублирующий ``unp`` не вводится — ``tax_id``
    # уже семантически УНП.
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_organizations_active_name", "is_active", "legal_name"),
    )


class OrganizationMembership(Base, TimestampMixin):
    """Explicit user-to-organization membership.

    Membership rows are never inferred from the free-text ``User.company``.
    """

    __tablename__ = "organization_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        pg_enum(OrganizationRole, "organization_role"),
        nullable=False,
        default=OrganizationRole.BUYER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        Index("ix_organization_memberships_user_status", "user_id", "is_active"),
        Index("ix_organization_memberships_org_status", "organization_id", "is_active"),
    )


class OrganizationPricingAgreement(Base, TimestampMixin):
    """Organization-level currency and fixed-rate terms."""

    __tablename__ = "organization_pricing_agreements"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_currency: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    fixed_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_rates.id"), nullable=True
    )
    agreement_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OrganizationBrandTerm(Base, TimestampMixin):
    """Organization-level discount for one brand."""

    __tablename__ = "organization_brand_terms"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        primary_key=True,
    )
    discount_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class OrganizationAddress(Base, UUIDPrimaryKey, TimestampMixin):
    """Optional legal, delivery, or pickup location for an organization."""

    __tablename__ = "organization_addresses"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="DELIVERY")
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_line: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="BY", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_organization_addresses_org_kind", "organization_id", "kind"),
        UniqueConstraint(
            "organization_id", "kind", "address_line", name="uq_org_address_line_kind"
        ),
    )


__all__ = [
    "Organization",
    "OrganizationAddress",
    "OrganizationBrandTerm",
    "OrganizationMembership",
    "OrganizationPricingAgreement",
]
