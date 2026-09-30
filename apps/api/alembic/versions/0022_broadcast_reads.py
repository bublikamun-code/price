"""Broadcast notifications: per-user read state (notification_reads).

ARCHITECTURE_PLAN.md §16 п.39. Broadcast-уведомления (user_id IS NULL — лиды
с лендинга менеджерам) видны всем менеджерам, но колонка ``is_read`` у них
одна на всех: PATCH read-all и per-item read не могли «закрыть» лид в ленте
конкретного менеджера (найдено GUI-тестом 30.09).

Решение: колонка ``is_read`` остаётся состоянием только личных уведомлений;
персональное прочтение broadcast хранится в ``notification_reads`` — по строке
на (notification, user). Записи не имеют самостоятельной ценности вне
родительской строки, поэтому оба FK — CASCADE (уведомление/юзер удалён →
read-строка не нужна).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_broadcast_reads"
down_revision: str | Sequence[str] | None = "0021_product_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_reads"),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="fk_notification_reads_notification_id_notifications",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_notification_reads_user_id_users",
            ondelete="CASCADE",
        ),
        # Один read-факт на (уведомление, юзер): идемпотентность повторных
        # PATCH /read и ON CONFLICT DO NOTHING в read-all.
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_notif_user"),
    )
    # read-all / точечные выборки идут по юзеру; (notification_id, user_id)
    # уже покрыт уникальным констрейнтом.
    op.create_index("ix_notification_reads_user", "notification_reads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_reads_user", table_name="notification_reads")
    op.drop_table("notification_reads")
