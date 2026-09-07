"""users.must_change_password + sessions.rotated_at/superseded_by_hash

Аудит 2026-09-06:
  - users.must_change_password — флаг принудительной смены временного пароля
    (§16 п.19): выставляется при создании клиента / сбросе пароля менеджером,
    снимается в POST /api/v1/auth/change-password. См. app/models/user.py.
  - sessions.rotated_at + sessions.superseded_by_hash — grace-окно ротации
    refresh-токена (гонка параллельных refresh из нескольких вкладок).
    См. app/services/auth.py (refresh) и settings.refresh_grace_seconds.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0008_pwd_change_grace"
down_revision: str | Sequence[str] | None = "0007_sync_drift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("superseded_by_hash", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "superseded_by_hash")
    op.drop_column("sessions", "rotated_at")
    op.drop_column("users", "must_change_password")
