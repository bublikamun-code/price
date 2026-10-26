"""Durable-очередь писем: таблица email_outbox (NOTIF-01).

ARCHITECTURE_PLAN.md §5.2 (email_outbox), §20.1 (Notification Hub, канал email).

Зачем: ``queue_email`` ставил Celery-задачу сразу в брокер — сбой брокера между
ответом HTTP и ``.delay()`` терял письмо (в т.ч. ссылку восстановления пароля)
безвозвратно. Теперь письмо фиксируется строкой PENDING до диспетча задачи;
свипер ``requeue_stuck_emails`` (beat, §7.2-паттерн reconcile) реэнквитит
зависшие строки. Статусы — свободные строки (как ``Notification.type``):
PENDING/SENT/FAILED/SKIPPED — см. докстринг модели.

Только ``CREATE TABLE`` + один UNIQUE-индекс (ни DROP, ни ALTER) — миграция
безопасна для существующих данных и полностью обратима. Колонка ``to`` —
зарезервированное слово SQL, SQLAlchemy/Alembic квотируют его автоматически.

ORM-декларация — app/models/system.py (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_email_outbox"
down_revision: str | Sequence[str] | None = "0025_add_missing_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="PENDING"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    # UNIQUE на dedupe_key (NULL не конфликтует — письма без дедупликации
    # свободно вставляются): ON CONFLICT (dedupe_key) DO NOTHING даёт
    # «ровно одну строку» при конкурентной постановке с тем же ключом.
    op.create_index(
        "uq_email_outbox_dedupe_key", "email_outbox", ["dedupe_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_email_outbox_dedupe_key", table_name="email_outbox")
    op.drop_table("email_outbox")
