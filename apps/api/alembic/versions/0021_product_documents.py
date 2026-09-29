"""Product documents: bind FileAsset to product/series + validity date.

ARCHITECTURE_PLAN.md §16 п.38 (этап 3 роадмапа «Документы на товар»):
сертификаты и datasheets — это те же ``file_assets``, но с привязкой к товару
или серии и со сроком действия. Привязка nullable со ``SET NULL`` — как
``brand_id``: удаление товара/серии не должно терять сам документ из архива.

Enum-значения добавляются на текущей голове (аддитивно), а не правкой уже
применённой миграции 0001 — PostgreSQL не позволяет удалять значения enum, поэтому
downgrade оставляет их на месте (паттерн 0014_user_role_admin).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_product_documents"
down_revision: str | Sequence[str] | None = "0020_media_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Список товаров/серий в карточке: product detail запрашивает документы на
    # каждый просмотр, поэтому FK-колонки индексируем сразу.
    op.add_column(
        "file_assets",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "file_assets",
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "file_assets",
        sa.Column("valid_until", sa.Date(), nullable=True),
    )
    op.create_foreign_key(
        "fk_file_assets_product_id_products",
        "file_assets",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_file_assets_series_id_series",
        "file_assets",
        "series",
        ["series_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_file_assets_product_id", "file_assets", ["product_id"]
    )
    op.create_index("ix_file_assets_series_id", "file_assets", ["series_id"])
    # ADD VALUE не может выполняться в транзакции в старых PG; начиная с PG 12 —
    # может, пока новое значение в этой же транзакции не используется (0014).
    op.execute("ALTER TYPE file_asset_type ADD VALUE IF NOT EXISTS 'CERTIFICATE'")
    op.execute("ALTER TYPE file_asset_type ADD VALUE IF NOT EXISTS 'DATASHEET'")


def downgrade() -> None:
    op.drop_index("ix_file_assets_series_id", table_name="file_assets")
    op.drop_index("ix_file_assets_product_id", table_name="file_assets")
    op.drop_constraint("fk_file_assets_series_id_series", "file_assets", type_="foreignkey")
    op.drop_constraint("fk_file_assets_product_id_products", "file_assets", type_="foreignkey")
    op.drop_column("file_assets", "valid_until")
    op.drop_column("file_assets", "series_id")
    op.drop_column("file_assets", "product_id")
    # PostgreSQL не умеет удалять значения enum без пересоздания типа и всех
    # зависимых объектов. Аддитивные значения остаются (паттерн 0014).
