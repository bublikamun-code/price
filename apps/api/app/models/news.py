"""Новости (публичная лента). См. ARCHITECTURE_PLAN.md §5."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import NewsType, pg_enum


class News(Base, TimestampMixin, UUIDPrimaryKey):
    """Новость / анонс нового продукта для клиентской ленты."""
    __tablename__ = "news"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NewsType] = mapped_column(
        pg_enum(NewsType, "news_type"), nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Индексы созданы миграцией 0004; объявлены в модели ради alembic check
    # (аудит 2026-09-06 §3: защита от дрейфа моделей → миграций).
    __table_args__ = (
        Index("ix_news_published_at", published_at.desc()),
        Index("ix_news_is_active", "is_active"),
    )
