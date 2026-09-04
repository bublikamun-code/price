"""add product_photos table

Revision ID: c4f9a2b71d3e
Revises: 0004_add_news
Create Date: 2026-09-04

Галерея дополнительных фото товара (§6): ключи webp из бакета фото серий,
``photos-product/{product_id}/{uuid8}.webp``. См. app/models/catalog.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "c4f9a2b71d3e"
down_revision: Union[str, Sequence[str], None] = "0004_add_news"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_photos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("photo_key", sa.String(512), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
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
        sa.UniqueConstraint(
            "product_id", "photo_key", name="uq_product_photos_product_key"
        ),
    )
    op.create_index(
        "ix_product_photos_product", "product_photos", ["product_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_product_photos_product", table_name="product_photos")
    op.drop_table("product_photos")
