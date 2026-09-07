"""add users.telegram_id

Revision ID: 0006_user_telegram
Revises: 0005_add_banners
Create Date: 2026-09-05

Колонка telegram_id (BigInteger, unique, nullable) — поле модели User
добавлено в 7412363 (§16 п.27, Telegram Mini App), но миграция не была
создана; из-за дрейфа схемы не поднималась свежая БД (seed/login падали
с UndefinedColumn). См. app/models/user.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0006_user_telegram"
down_revision: Union[str, Sequence[str], None] = "0005_add_banners"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_users_telegram_id", "users", ["telegram_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_id")
