"""products.attributes JSONB (характеристики товара, §5)

Revision ID: 0002_product_attributes
Revises: 0001_initial
Create Date: 2026-08-12

Добавляет колонку ``products.attributes`` (JSONB) и GIN-индекс
``jsonb_path_ops`` для фильтрации по характеристикам через оператор ``@>``.
См. ARCHITECTURE_PLAN.md §5 (products).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0002_product_attributes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_products_attributes",
        "products",
        ["attributes"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"attributes": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_products_attributes", table_name="products")
    op.drop_column("products", "attributes")
