"""add news table

Revision ID: 0004_add_news
Revises: 47c20b0f969c
Create Date: 2026-09-03

Таблица новостей (публичная лента) + PostgreSQL ENUM news_type.
См. app/models/news.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0004_add_news"
down_revision: Union[str, Sequence[str], None] = "47c20b0f969c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    news_type = postgresql.ENUM(
        "NEWS", "NEW_PRODUCT", name="news_type", create_type=True
    )
    news_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "news",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("type", news_type, nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
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
    op.create_index("ix_news_published_at", "news", [sa.text("published_at DESC")])
    op.create_index("ix_news_is_active", "news", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_news_is_active", table_name="news")
    op.drop_index("ix_news_published_at", table_name="news")
    op.drop_table("news")
    postgresql.ENUM(name="news_type").drop(op.get_bind(), checkfirst=True)
