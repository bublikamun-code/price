"""Коммерческое предложение (КП). Этап 8 роадмапа; см. docs/FEATURES_ROADMAP.md.

КП — документ менеджера с НЕСТАНДАРТНЫМИ ценами (override) и сроком действия:
  * ``quotes.total_amount`` в DRAFT пересчитывается при каждой правке позиций
    («не заморожен»), а при SEND фиксируется окончательно — дальше КП
    читается, но не редактируется (DRAFT-only edit/delete, §этап 8);
  * позиции ``quote_items`` — снапшот: ``sku``/``name`` копируются из каталога
    в момент добавления, ``unit_price`` — цена из КП (не базовая), и именно
    она переезжает в ``order_items.unit_price`` при accept (без прайс-логики);
  * номер ``КП-YYYY-NNNNNN`` присваивается только при SEND (у DRAFT номера
    нет — черновик не документ); ``seq`` — PG-последовательность
    ``quotes_seq_seq`` (nextval, а не MAX+1 — тот же урок, что у
    ``invoices_seq_seq``, §16 п.9);
  * срок действия ``valid_until`` обязателен к моменту SEND; истёкшее SENT-КП
    помечается EXPIRED beat-задачей и лениво при чтении/accept.

Номер печатается как ``КП-{year}-{seq:06d}``; последовательность сквозная,
год входит только в отображение (см. app/models/invoice.py).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import QuotePdfStatus, QuoteStatus, pg_enum

# PG-последовательность сквозных номеров КП (создаётся миграцией 0029).
# Объявлена в metadata → Base.metadata.create_all (тестовая схема) создаёт
# её автоматически.
quotes_seq_numbering = Sequence("quotes_seq_seq", metadata=Base.metadata)


class Quote(Base, TimestampMixin, UUIDPrimaryKey):
    """Коммерческое предложение организации (этап 8 роадмапа)."""

    __tablename__ = "quotes"

    # RESTRICT: организация с историей КП не удаляется каскадом —
    # коммерческие документы переживают аккуратную чистку данных.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Менеджер, создавший КП; адресат уведомлений accept/reject. SET NULL:
    # удаление пользователя не должно терять сам документ.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[QuoteStatus] = mapped_column(
        pg_enum(QuoteStatus, "quote_status"),
        nullable=False,
        default=QuoteStatus.DRAFT,
    )
    # Срок действия обязателен к моменту SEND (валидация сервиса), в DRAFT —
    # заполняется менеджером или при правке.
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Номер и сквозной номер присваиваются только при SEND (у DRAFT их нет:
    # черновик — не документ, нумерация не «сжигается»).
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # DRAFT: пересчитывается при каждой правке позиций; SEND: заморозка.
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    # КП всегда в BYN (цены override менеджера, пересчёт по курсу не применяется).
    currency_code: Mapped[str] = mapped_column(String(3), default="BYN", nullable=False)

    # Состояние PDF-рендера — та же колонка-вместо-Redis, что у счёта (§10).
    # Рендер синхронный по запросу менеджера; повторный вызов перерендеривает
    # и подменяет FileAsset.
    pdf_status: Mapped[QuotePdfStatus] = mapped_column(
        pg_enum(QuotePdfStatus, "quote_pdf_status"),
        nullable=False,
        default=QuotePdfStatus.PENDING,
    )
    pdf_file_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Optimistic concurrency (If-Match на PATCH/send).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # Позиции КП: каскад удаляется вместе с КП (delete-orphan — замена списка
    # позиций при edit делает репозиторий через коллекцию).
    items: Mapped[list["QuoteItem"]] = relationship(
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteItem.created_at",
    )

    __table_args__ = (
        # Номер уникален глобально (uq_quotes_number); seq уникален среди
        # присвоенных (NULL у DRAFT в PG-уникальности не участвуют).
        UniqueConstraint("seq", name="uq_quotes_seq"),
        UniqueConstraint("number", name="uq_quotes_number"),
        # Списки «свежие сверху» (клиент и менеджер) — org + created_at DESC.
        Index("ix_quotes_org_created", "organization_id", text("created_at DESC")),
        Index("ix_quotes_status", "status"),
    )


class QuoteItem(Base, UUIDPrimaryKey):
    """Позиция КП: замороженный снапшот товара и цена из КП (не прайс)."""

    __tablename__ = "quote_items"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT: товар, вошедший в КП, не удаляется из БД (снапшот — страховка,
    # но FK-целостность сохраняем, как у client_sku_mappings, §16 п.43 п.8).
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # Снапшот sku/name на момент добавления позиции: переименование товара в
    # каталоге не переписывает уже составленное КП.
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)

    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    # Цена из КП (override менеджера), 2 знака — как order_items.unit_price.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Комментарий позиции переезжает в order_items.note при accept.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    quote: Mapped[Quote] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("qty >= 1", name="ck_quote_items_qty_positive"),
        CheckConstraint("unit_price > 0", name="ck_quote_items_unit_price_positive"),
        # Карточка КП читает позиции по quote_id в порядке добавления.
        Index("ix_quote_items_quote_created", "quote_id", "created_at"),
    )


__all__ = ["Quote", "QuoteItem", "quotes_seq_numbering"]
