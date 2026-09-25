"""Add commercial scope and optimistic concurrency to carts.

Existing carts intentionally remain in the legacy USER scope. The partial
indexes preserve one cart per legacy user while allowing one cart per active
organization without treating PostgreSQL NULL values as equal.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_cart_org_scope_version"
down_revision: str | Sequence[str] | None = "0015_order_delivery_address_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "carts",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_carts_organization_id",
        "carts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "carts",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.drop_constraint("uq_carts_user_id", "carts", type_="unique")
    op.create_index(
        "uq_carts_user_scope",
        "carts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_carts_user_org",
        "carts",
        ["user_id", "organization_id"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_cart_items_quantity_positive",
        "cart_items",
        "quantity > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cart_items_quantity_positive", "cart_items", type_="check")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM carts
                WHERE organization_id IS NOT NULL
                GROUP BY user_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade scoped carts: a user has multiple organization carts';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM carts
                WHERE organization_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade scoped carts: organization carts must be merged or removed explicitly';
            END IF;
        END $$
        """
    )

    op.drop_index("uq_carts_user_org", table_name="carts")
    op.drop_index("uq_carts_user_scope", table_name="carts")
    op.create_unique_constraint("uq_carts_user_id", "carts", ["user_id"])
    op.drop_column("carts", "version")
    op.drop_constraint("fk_carts_organization_id", "carts", type_="foreignkey")
    op.drop_column("carts", "organization_id")
