"""initial schema: all tables per ARCHITECTURE_PLAN.md §5

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-11

Соответствует моделям в app/models/. Если модели меняются —
сначала обновить ARCHITECTURE_PLAN.md §5, затем сгенерировать
новую миграцию (make migrate-gen m="...").
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.types import CITEXT

# revision identifiers
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# ---------------- Enum-типы (имена = в app/models/enums.py) ----------------
ENUMS: dict[str, list[str]] = {
    "user_role": ["CLIENT", "MANAGER"],
    "stock_status": ["IN_STOCK", "PREORDER", "ARCHIVED"],
    "order_status": ["NEW", "IN_PROGRESS", "SHIPPED", "COMPLETED", "CANCELLED"],
    "import_mode": ["UPSERT", "REPLACE", "ARCHIVE_MISSING"],
    "price_list_version_status": ["QUEUED", "PROCESSING", "DONE", "FAILED"],
    "file_asset_type": ["BRAND_PDF", "CUSTOM_CSV", "PHOTO_ZIP", "OTHER"],
    "file_visibility": ["PUBLIC", "AUTHED", "MANAGER_ONLY"],
}


def _enum(name: str) -> sa.Enum:
    """Native postgres ENUM. Тип создаётся автоматически при CREATE TABLE
    (каждый enum используется ровно в одной таблице — конфликта нет)."""
    return sa.Enum(*ENUMS[name], name=name)


def _uuid(**kw) -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        **kw,
    )


# ---------------- Upgrade ----------------
def upgrade() -> None:
    # --- Расширения ---
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid (для PG<13)

    # Enum-типы создаются автоматически при создании таблиц (см. _enum()).

    # --- exchange_rates (без FK-зависимостей) ---
    op.create_table(
        "exchange_rates",
        _uuid(),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("scale", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("fetched_at", sa.Date, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'NBRB'")),
        sa.Column("is_manual", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            "currency_code", "fetched_at", "source",
            name="uq_rates_currency_date_source",
        ),
    )
    op.create_index(
        "ix_rates_currency_date", "exchange_rates",
        ["currency_code", sa.text("fetched_at DESC")],
    )

    # --- users ---
    op.create_table(
        "users",
        _uuid(),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("role", _enum("user_role"), nullable=False, server_default=sa.text("'CLIENT'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True)),
        sa.Column("display_currency", sa.String(3), nullable=False, server_default=sa.text("'BYN'")),
        sa.Column("fixed_rate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exchange_rates.id"), nullable=True),
        sa.Column("totp_secret", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # --- brands ---
    op.create_table(
        "brands",
        _uuid(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_brands_slug"),
    )

    # --- series ---
    op.create_table(
        "series",
        _uuid(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("photo_key", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- price_list_versions (нужен перед products) ---
    op.create_table(
        "price_list_versions",
        _uuid(),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("import_mode", _enum("import_mode"), nullable=False, server_default=sa.text("'UPSERT'")),
        sa.Column("status", _enum("price_list_version_status"), nullable=False,
                  server_default=sa.text("'QUEUED'")),
        sa.Column("rows_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_ok", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rows_error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_log_key", sa.String(512)),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default=sa.text("'BYN'")),
        sa.Column("rate_to_byn", sa.Numeric(12, 4), nullable=False, server_default="1"),
        sa.Column("rate_source", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- products ---
    op.create_table(
        "products",
        _uuid(),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("series_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("series.id", ondelete="SET NULL")),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("brands.id", ondelete="SET NULL")),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("override_price", sa.Numeric(12, 2)),
        sa.Column("stock_status", _enum("stock_status"), nullable=False,
                  server_default=sa.text("'IN_STOCK'")),
        sa.Column("price_list_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("price_list_versions.id")),
        sa.Column("external_1c_guid", sa.String(64)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("search_vector", postgresql.TSVECTOR),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_products_brand", "products", ["brand_id"])
    op.create_index("ix_products_series", "products", ["series_id"])
    op.create_index("ix_products_stock", "products", ["stock_status"])
    # Частичный unique на sku (среди не удалённых)
    op.create_index(
        "uq_products_sku_active", "products", ["sku"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # GIN для полнотекстового поиска
    op.create_index(
        "ix_products_search_vector", "products", ["search_vector"],
        postgresql_using="gin",
    )
    # Триграммы для «google-подобного» поиска по имени
    op.execute(
        "CREATE INDEX ix_products_name_trgm ON products USING gin (name gin_trgm_ops)"
    )

    # --- price_history (фича J) ---
    op.create_table(
        "price_history",
        _uuid(),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("override_price", sa.Numeric(12, 2)),
        sa.Column("price_list_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("price_list_versions.id")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_price_history_product_time", "price_history", ["product_id", "changed_at"])

    # --- user_brands (матрица скидок) ---
    op.create_table(
        "user_brands",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- favorites (фича A) ---
    op.create_table(
        "favorites",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- carts (фича D) ---
    op.create_table(
        "carts",
        _uuid(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default=sa.text("'Корзина'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- cart_items ---
    op.create_table(
        "cart_items",
        _uuid(),
        sa.Column("cart_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
    )

    # --- orders ---
    op.create_table(
        "orders",
        _uuid(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("status", _enum("order_status"), nullable=False, server_default=sa.text("'NEW'")),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default=sa.text("'BYN'")),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=False, server_default="1"),
        sa.Column("rate_source", sa.String(64)),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text),
        sa.Column("external_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orders_client_created", "orders", ["client_id", "created_at"])
    op.create_index("ix_orders_status", "orders", ["status"])

    # --- order_items ---
    op.create_table(
        "order_items",
        _uuid(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("product_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default=sa.text("'BYN'")),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- file_assets ---
    op.create_table(
        "file_assets",
        _uuid(),
        sa.Column("type", _enum("file_asset_type"), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("filename_display", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("brands.id", ondelete="SET NULL")),
        sa.Column("visibility", _enum("file_visibility"), nullable=False, server_default=sa.text("'AUTHED'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- sessions (refresh tokens) ---
    op.create_table(
        "sessions",
        _uuid(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String, nullable=False),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("ip", sa.String(45)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_hash"),
    )

    # --- consent_log ---
    op.create_table(
        "consent_log",
        _uuid(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- audit_log ---
    op.create_table(
        "audit_log",
        _uuid(),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_actor_time", "audit_log", ["actor_id", "created_at"])
    op.create_index("ix_audit_action_time", "audit_log", ["action", "created_at"])

    # --- notifications ---
    op.create_table(
        "notifications",
        _uuid(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("body", sa.Text),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("channel", postgresql.ARRAY(sa.String)),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_notif_user_unread", "notifications", ["user_id"],
        postgresql_where=sa.text("is_read = FALSE"),
    )


# ---------------- Downgrade ----------------
def downgrade() -> None:
    # Таблицы — в порядке, обратном зависимостям
    for table in [
        "notifications",
        "audit_log",
        "consent_log",
        "sessions",
        "file_assets",
        "order_items",
        "orders",
        "cart_items",
        "carts",
        "favorites",
        "user_brands",
        "price_history",
        "products",
        "price_list_versions",
        "series",
        "brands",
        "users",
        "exchange_rates",
    ]:
        op.drop_table(table)

    # Enum-типы
    for name in reversed(list(ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {name}")

    # Расширения оставляем (могут использоваться повторно при re-apply).
