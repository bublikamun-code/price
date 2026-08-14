"""Базовый класс для всех ORM-моделей.

См. ARCHITECTURE_PLAN.md §5:
  - id: UUID v7 (сортируемый) — пока UUID4, заменить на UUID7 при наличии pg_uuidv7
  - created_at / updated_at: TIMESTAMPTZ, авто
  - soft-delete через deleted_at (где применимо)
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Декларативный базовый класс SQLAlchemy 2.0."""

    pass


class TimestampMixin:
    """created_at / updated_at с автозаполнением на стороне БД."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKey:
    """UUID PK (пока UUID4, default в Python)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
