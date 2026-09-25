"""Заявки и корзина.

См. ARCHITECTURE_PLAN.md §5, §9, §16.1 (фичи C, D, E).
Критично: заморозка цен в order_items.unit_price + snapshot курса в order (§9, §17).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import OrderStatus, pg_enum

# PG-последовательность сквозных номеров заявок (nextval, аудит 2026-09-06):
# миграция 0009 создаёт её на существующей БД с START = MAX(seq)+1.
# Объявлена с metadata → Base.metadata.create_all (тестовая схема) создаёт
# её автоматически. Выдаёт уникальные значения при конкурентном оформлении —
# в отличие от MAX(seq)+1, падавшего по uq_orders_seq (см. §9).
orders_seq_numbering = Sequence("orders_seq_seq", metadata=Base.metadata)


class Cart(Base, TimestampMixin, UUIDPrimaryKey):
    """One persisted cart per user and commercial scope.

    ``organization_id is NULL`` is the legacy USER cart used by API v1 and
    remains separate from every organization cart created by API v2.
    """
    __tablename__ = "carts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    name: Mapped[str] = mapped_column(String(100), default="Корзина", nullable=False)

    __table_args__ = (
        Index(
            "uq_carts_user_scope",
            "user_id",
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
        Index(
            "uq_carts_user_org",
            "user_id",
            "organization_id",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
    )


class CartItem(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "cart_items"

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # фича E

    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
    )


class Order(Base, TimestampMixin, UUIDPrimaryKey):
    """Заявка.

    Заморозка курса (§17.2, Уровень 3): exchange_rate + currency_code + rate_source
    фиксируются на момент оформления и НЕ меняются.
    """
    __tablename__ = "orders"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Organization ownership is added expand-first. NULL means the order is
    # still in the legacy user-ownership compatibility phase.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"),
        nullable=False,
        default=OrderStatus.NEW,
    )

    currency_code: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    exchange_rate: Mapped[float] = mapped_column(Numeric(12, 4), default=1, nullable=False)
    rate_source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 'FIXED' | 'NBRB_<date>'

    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Способ получения: 'pickup' (самовывоз) | 'delivery' (доставка).
    delivery_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pickup", server_default="pickup"
    )
    # Название пункта самовывоза / пометка доставки.
    delivery_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Structured delivery projection; nullable during the v1→v2 transition.
    delivery_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # API v2 accepts an opaque delivery address UUID. It is persisted as a
    # snapshot reference without changing the legacy structured address fields.
    delivery_address_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    delivery_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_preferred_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 1С (§18)

    # Сквозной номер заявки («№123» вместо обрезанного UUID). Присваивается
    # при создании из PG-последовательности orders_seq_seq (nextval —
    # атомарно при конкурентном оформлении, миграция 0009); для существующих
    # строк — backfill миграцией. Возможны «дыры» при откате транзакции.
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optimistic concurrency token; manager writes may require If-Match.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __table_args__ = (
        UniqueConstraint("seq", name="uq_orders_seq"),
        # Созданы миграцией 0001; объявлены в модели ради alembic check.
        Index("ix_orders_client_created", "client_id", "created_at"),
        Index("ix_orders_organization_created", "organization_id", "created_at"),
        Index("ix_orders_status", "status"),
    )


class OrderItem(Base, UUIDPrimaryKey):
    """Позиция заявки. unit_price — ЗАМОРОЖЕНА (§9), не пересчитывается."""
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {sku,name,brand,...}
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)  # заморожено
    currency_code: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # фича E
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrderIdempotency(Base, UUIDPrimaryKey):
    """Ключ повторного submit-запроса и его канонический fingerprint.

    Запись резервируется в одной транзакции с заказом. Повтор с тем же ключом
    и fingerprint возвращает исходный заказ; другой fingerprint — конфликт.
    """
    __tablename__ = "order_idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_order_idempotency_user_key",
        ),
    )
