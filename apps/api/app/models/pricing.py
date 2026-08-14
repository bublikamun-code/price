"""Курсы валют и матрица скидок.

См. ARCHITECTURE_PLAN.md §5, §8, §17.
"""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey


class ExchangeRate(Base, UUIDPrimaryKey):
    """Курсы валют. Источник: НБ РБ (ежедневно) или ручной ввод менеджера.

    См. §17.4. rate — за `scale` единиц валюты к BYN (для RUB scale=100).
    """
    __tablename__ = "exchange_rates"

    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    scale: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    fetched_at: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="NBRB", nullable=False)
    is_manual: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "currency_code", "fetched_at", "source", name="uq_rates_currency_date_source"
        ),
    )


class UserBrand(Base, TimestampMixin):
    """Матрица скидок: связь Клиент → Бренд → Процент скидки (§5, §8).

    Приоритет цены (§8): override_price > base*(1-discount) > base.
    """
    __tablename__ = "user_brands"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True
    )
    discount_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
