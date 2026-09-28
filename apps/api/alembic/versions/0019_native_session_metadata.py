"""Add native client metadata to sessions.

ARCHITECTURE_PLAN.md §16 п.36: the session journal must show which device a
session belongs to, so the SwiftUI/Compose clients can offer "log out this
device". All four columns are nullable on purpose — web logins leave them NULL
and the journal omits empty values rather than inventing a device name.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_native_session_metadata"
down_revision: str | Sequence[str] | None = "0018_fix_constraint_drift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("client_type", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("device_name", sa.String(length=128), nullable=True))
    op.add_column("sessions", sa.Column("os_name", sa.String(length=64), nullable=True))
    op.add_column("sessions", sa.Column("app_version", sa.String(length=32), nullable=True))
    # Journal reads a user's own active sessions ordered by recency; the
    # existing index covers user_id but not the revoked/expires filter.
    op.create_index(
        "ix_sessions_user_id_revoked",
        "sessions",
        ["user_id", "revoked"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id_revoked", table_name="sessions")
    op.drop_column("sessions", "app_version")
    op.drop_column("sessions", "os_name")
    op.drop_column("sessions", "device_name")
    op.drop_column("sessions", "client_type")
