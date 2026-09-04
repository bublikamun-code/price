"""add banners table

Revision ID: 0005_add_banners
Revises: c4f9a2b71d3e
Create Date: 2026-09-04

Баннеры главной страницы + PostgreSQL ENUM banner_link_type, banner_position.
См. app/models/banner.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0005_add_banners"
down_revision: Union[str, Sequence[str], None] = "c4f9a2b71d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Типы создаём вручную (checkfirst — идемпотентно), а в create_table
    # передаём create_type=False, иначе Alembic эмитит CREATE TYPE второй раз.
    banner_link_type = postgresql.ENUM(
        "NONE", "PRODUCT", "NEWS", name="banner_link_type", create_type=False
    )
    banner_link_type.create(op.get_bind(), checkfirst=True)
    banner_position = postgresql.ENUM(
        "PROMO", "NEW", name="banner_position", create_type=False
    )
    banner_position.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "banners",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("subtitle", sa.String(500), nullable=True),
        sa.Column("image_key", sa.String(1024), nullable=True),
        sa.Column(
            "link_type",
            banner_link_type,
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("link_value", sa.String(255), nullable=True),
        sa.Column("position", banner_position, nullable=False),
        sa.Column(
            "sort",
            sa.Integer,
            nullable=False,
            server_default="0",
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
    op.create_index(
        "ix_banners_position_active",
        "banners",
        ["position", "is_active", "sort"],
    )


def downgrade() -> None:
    op.drop_index("ix_banners_position_active", table_name="banners")
    op.drop_table("banners")
    postgresql.ENUM(name="banner_link_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="banner_position").drop(op.get_bind(), checkfirst=True)
