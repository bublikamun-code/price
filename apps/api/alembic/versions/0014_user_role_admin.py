"""Add the ADMIN user role to the PostgreSQL enum.

This is an additive migration: it does not rewrite historical migrations or
change existing rows. PostgreSQL enum values must be added at the current
head rather than by editing an already-applied migration.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "0014_user_role_admin"
down_revision: str | Sequence[str] | None = "0013_organization_expand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value without recreating the type and
    # all dependent objects. Keep the additive value in place on downgrade.
    pass
