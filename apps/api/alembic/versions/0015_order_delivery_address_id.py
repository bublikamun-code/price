"""Persist the API v2 delivery address reference snapshot.

The UUID is intentionally opaque here: address-resource ownership and mutation
are outside this vertical slice. Existing v1 delivery fields and routes remain
unchanged.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_order_delivery_address_id"
down_revision: str | Sequence[str] | None = "0014_user_role_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "delivery_address_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "delivery_address_id")
