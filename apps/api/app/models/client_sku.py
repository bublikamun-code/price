"""Кросс-справочник клиентских артикулов (этап 7 роадмапа — §16 п.43).

Справочник «артикул клиента → наш SKU» — свойство организации: участники одной
организации делят связки, у соло-клиента (USER-скоуп) режима нет. ``client_sku``
— CITEXT: сравнение регистронезависимо («Привод ГТУ-2» = «привод гту-2»),
хранится как ввёл клиент; trim делает сервис. ``product_id`` — FK **без
CASCADE** (RESTRICT): товар с архивацией не удаляется из БД, маппинг переживает
архив — apply на архивный товар даёт unknown «Товар в архиве», клиент перемапит
(§16 п.43 п.4/8).
"""
import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.db.types import CITEXT


class ClientSkuMapping(Base, UUIDPrimaryKey, TimestampMixin):
    """Одна связка «артикул клиента → товар каталога» внутри организации."""

    __tablename__ = "client_sku_mappings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # CITEXT: дубль (org, client_sku) невозможен ни в каком регистре; trim —
    # на сервисной границе, храним как ввёл клиент.
    client_sku: Mapped[str] = mapped_column(CITEXT, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optimistic concurrency для PATCH If-Match (§16 п.43 п.7).
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "client_sku", name="uq_client_sku_mappings_org_sku"
        ),
        # Список справочника — свежие связки сверху. created_at приходит из
        # TimestampMixin, поэтому DESC — текстом (паттерн ix_users_role_created).
        Index(
            "ix_client_sku_mappings_org_created",
            "organization_id",
            text("created_at DESC"),
        ),
    )


__all__ = ["ClientSkuMapping"]
