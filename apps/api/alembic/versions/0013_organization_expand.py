"""Add explicit organization ownership primitives without legacy backfill."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0013_organization_expand"
down_revision: str | Sequence[str] | None = "0012_order_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(**kwargs) -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        **kwargs,
    )


def upgrade() -> None:
    organization_role = sa.Enum(
        "OWNER", "BUYER", "CONTACT", "VIEWER", name="organization_role"
    )

    op.create_table(
        "organizations",
        _uuid(),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column(
            "country_code", sa.String(length=2), nullable=False, server_default="BY"
        ),
        sa.Column(
            "default_currency", sa.String(length=3), nullable=False, server_default="BYN"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("legal_address", sa.Text(), nullable=True),
        sa.Column("legal_email", sa.String(length=320), nullable=True),
        sa.Column("legal_phone", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_organizations_active_name",
        "organizations",
        ["is_active", "legal_name"],
    )

    op.create_table(
        "organization_memberships",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role",
            organization_role,
            nullable=False,
            server_default=sa.text("'BUYER'"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_organization_memberships_user_status",
        "organization_memberships",
        ["user_id", "is_active"],
    )
    op.create_index(
        "ix_organization_memberships_org_status",
        "organization_memberships",
        ["organization_id", "is_active"],
    )

    op.create_table(
        "organization_pricing_agreements",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "display_currency", sa.String(length=3), nullable=False, server_default="BYN"
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "fixed_rate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exchange_rates.id"),
            nullable=True,
        ),
        sa.Column("agreement_reference", sa.String(length=128), nullable=True),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "organization_brand_terms",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "discount_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "organization_addresses",
        _uuid(),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="DELIVERY"
        ),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address_line", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column(
            "country_code", sa.String(length=2), nullable=False, server_default="BY"
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_organization_addresses_org_kind",
        "organization_addresses",
        ["organization_id", "kind"],
    )
    op.create_unique_constraint(
        "uq_org_address_line_kind",
        "organization_addresses",
        ["organization_id", "kind", "address_line"],
    )

    # Expand pointers only. Existing users/orders remain in legacy mode until
    # an explicit membership/backfill workflow is reviewed and run.
    op.add_column(
        "users",
        sa.Column(
            "active_organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_users_active_organization_id",
        "users",
        "organizations",
        ["active_organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_users_active_organization_id",
        "users",
        ["active_organization_id"],
    )

    op.add_column(
        "orders",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_orders_organization_id",
        "orders",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_orders_organization_created",
        "orders",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_organization_created", table_name="orders")
    op.drop_constraint("fk_orders_organization_id", "orders", type_="foreignkey")
    op.drop_column("orders", "organization_id")

    op.drop_index("ix_users_active_organization_id", table_name="users")
    op.drop_constraint("fk_users_active_organization_id", "users", type_="foreignkey")
    op.drop_column("users", "active_organization_id")

    op.drop_constraint("uq_org_address_line_kind", "organization_addresses", type_="unique")
    op.drop_index("ix_organization_addresses_org_kind", table_name="organization_addresses")
    op.drop_table("organization_addresses")
    op.drop_table("organization_brand_terms")
    op.drop_table("organization_pricing_agreements")
    op.drop_index(
        "ix_organization_memberships_org_status", table_name="organization_memberships"
    )
    op.drop_index(
        "ix_organization_memberships_user_status", table_name="organization_memberships"
    )
    op.drop_table("organization_memberships")
    op.drop_index("ix_organizations_active_name", table_name="organizations")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS organization_role")
