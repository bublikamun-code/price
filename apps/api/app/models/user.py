"""Пользователи и связанные таблицы: sessions, consent_log, favorites.

См. ARCHITECTURE_PLAN.md §5, §16.1 (фичи A, H, I).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.db.types import CITEXT
from app.models.enums import UserRole, pg_enum


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.CLIENT,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Согласие на обработку ПДн (§16 п.10)
    consent_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Мультивалютность (§17): display-валюта + зафиксированный курс
    display_currency: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)
    fixed_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_rates.id"), nullable=True
    )

    # 2FA для менеджера (фича H)
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)

    # Opt-in на дайджест изменения цен (§20.4): включён + источники отслеживания.
    # Источники: 'cart', 'favorite', 'orders'. По умолчанию все три.
    price_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    price_digest_sources: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=lambda: ["cart", "favorite", "orders"],
        server_default=text("ARRAY['cart','favorite','orders']::varchar[]"),
        nullable=False,
    )


class Session(Base, UUIDPrimaryKey):
    """Refresh-токены (хэш). См. §11. Один активный токен на устройство."""
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsentLog(Base, UUIDPrimaryKey):
    """Журнал принятия согласия на обработку ПДн (§16 п.10)."""
    __tablename__ = "consent_log"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Favorite(Base):
    """Избранное клиента (фича A). Источник для PRICE_CHANGED_DIGEST (§20)."""
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),)
