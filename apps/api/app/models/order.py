"""Заявки и корзина.

См. ARCHITECTURE_PLAN.md §5, §9, §16.1 (фичи C, D, E).
Критично: заморозка цен в order_items.unit_price + snapshot курса в order (§9, §17).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import OrderStatus, pg_enum


class Cart(Base, TimestampMixin, UUIDPrimaryKey):
    """Корзина клиента (фича D — сохранённые корзины). Одна активная + именованные."""
    __tablename__ = "carts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), default="Корзина", nullable=False)


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
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 1С (§18)


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
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)  # заморожено
    currency_code: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # фича E
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
