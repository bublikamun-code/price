"""pg_trgm GIN-индекс по products.sku для поиска-подстроки (§5.2)

Revision ID: 0003_products_sku_trgm
Revises: 863ddb771b92
Create Date: 2026-08-14

Поиск каталога (``q``) идёт по ``sku ILIKE '%…%' OR name ILIKE '%…%'``.
GIN trgm-индекс по ``name`` существует с 0001; этот добавляет индекс по
``sku``, чтобы обе ветки условия шли bitmap-сканом, а не seq scan.
Оба индекса объявлены в ``Product.__table_args__`` (раньше name-индекс
был только в raw SQL 0001 → рассинхрон с alembic autogenerate).
См. ARCHITECTURE_PLAN.md §5.2 (products, индексы).
"""
from alembic import op

# revision identifiers
revision = "0003_products_sku_trgm"
down_revision = "863ddb771b92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # name-индекс уже создан в 0001; на всякий случай идемпотентно ensured
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_name_trgm "
        "ON products USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_sku_trgm "
        "ON products USING gin (sku gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_sku_trgm")
