"""Каталог: бренды, серии, товары, версии прайса, история цен.

См. ARCHITECTURE_PLAN.md §5, §7, §16.1 (фича J — история цены).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import ImportMode, PriceListVersionStatus, StockStatus, pg_enum


class Brand(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class Series(Base, TimestampMixin, UUIDPrimaryKey):
    """Серия товаров. Фото привязано к серии (§3 ТЗ, колонка 8 CSV)."""
    __tablename__ = "series"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    photo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Product(Base, TimestampMixin, UUIDPrimaryKey):
    """Товар. См. §5.

    Цена:
      base_price     — базовая розничная (в BYN, уже конвертированная по курсу прайса §17)
      override_price — жёсткая цена со скидкой из CSV (приоритет, §8)
    Soft-delete: deleted_at (§7, ARCHIVE_MISSING).
    """
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("series.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    base_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    override_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    stock_status: Mapped[StockStatus] = mapped_column(
        pg_enum(StockStatus, "stock_status"),
        nullable=False,
        default=StockStatus.IN_STOCK,
    )

    # Остаток на складе, шт. Nullable: NULL — остаток не заведён
    # (колонка в CSV отсутствовала / менеджер не заполнял).
    stock_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)

    price_list_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_list_versions.id"), nullable=True
    )
    external_1c_guid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Полнотекстовый поиск (§5). Наполняется триггером/в сервисе (Этап 3).
    search_vector = mapped_column(TSVECTOR, nullable=True)

    # Характеристики товара (§5): цвет, модули, IP-рейтинг, габариты и т.п.
    # Состав зависит от категории. Фильтрация через JSONB-операторы (@>, ->>).
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        # Артикул уникален среди НЕ удалённых
        Index(
            "uq_products_sku_active",
            "sku",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_products_brand", "brand_id"),
        Index("ix_products_series", "series_id"),
        Index("ix_products_stock", "stock_status"),
        Index(
            "ix_products_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_products_attributes",
            "attributes",
            postgresql_using="gin",
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ),
        # pg_trgm GIN для поиска-подстроки (ILIKE '%q%') по каталогу (§5.2)
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_sku_trgm",
            "sku",
            postgresql_using="gin",
            postgresql_ops={"sku": "gin_trgm_ops"},
        ),
    )


class PriceListVersion(Base, UUIDPrimaryKey):
    """Версия импорта прайса. См. §5, §17 (курс прайса)."""
    __tablename__ = "price_list_versions"

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    import_mode: Mapped[ImportMode] = mapped_column(
        pg_enum(ImportMode, "import_mode"),
        nullable=False,
        default=ImportMode.UPSERT,
    )
    status: Mapped[PriceListVersionStatus] = mapped_column(
        pg_enum(PriceListVersionStatus, "price_list_version_status"),
        nullable=False,
        default=PriceListVersionStatus.QUEUED,
    )
    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_error: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_log_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Курс прайса при импорте (§17.2, Уровень 1)
    base_currency: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    rate_to_byn: Mapped[float] = mapped_column(Numeric(12, 4), default=1, nullable=False)
    rate_source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Аудит отката версии (§16 п.14): заполнено — версия уже откачена.
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class PriceHistory(Base, UUIDPrimaryKey):
    """История изменения цены по SKU (фича J). Пишется при каждом импорте."""
    __tablename__ = "price_history"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    base_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    override_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_list_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_list_versions.id"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_price_history_product_time", "product_id", "changed_at"),)
