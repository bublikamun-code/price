"""Счёт на оплату (1:1 с заказом). См. ARCHITECTURE_PLAN.md §5.2, §10, §16 п.40.

Счёт — **замороженный документ**: суммы, позиции и цены копируются из
заказа в момент выставления и никогда не пересчитываются (в т.ч. по курсу
НБ РБ — «пересчитать по курсу» §16 п.7 действует только в корзине/черновике).
Статусы счёта и заказа независимы (§16 п.40 п.8/п.9), поэтому у счёта своя
``version`` для optimistic concurrency (``If-Match`` на счёте сверяет её, а не
версию заказа).

Номер печатается как ``СЧ-YYYY-NNNNNN``; ``seq`` берётся из PG-последовательности
``invoices_seq_seq`` (nextval, а не MAX+1 — тот же урок, что у
``orders_seq_seq``, §16 п.9). Сама последовательность глобальная, год входит
только в отображение и не сбрасывается: сброс ломал бы аудит и нумерацию уже
выставленных счетов.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import InvoicePdfStatus, InvoiceStatus, pg_enum

# PG-последовательность сквозных номеров счетов (создаётся миграцией 0023 на
# существующей БД с START = MAX(seq)+1). Объявлена в metadata →
# Base.metadata.create_all (тестовая схема) создаёт её автоматически.
invoices_seq_numbering = Sequence("invoices_seq_seq", metadata=Base.metadata)


class Invoice(Base, TimestampMixin, UUIDPrimaryKey):
    """Счёт на оплату, замороженный на момент выставления (§16 п.40)."""

    __tablename__ = "invoices"

    # 1:1 с заказом: второй счёт по заказу невозможен (переоформление —
    # вне этапа). ON DELETE CASCADE согласован с order_items: счёт без
    # заказа не имеет смысла.
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # Зафиксированный печатный номер; не пересчитывается при смене статуса.
    number: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[InvoiceStatus] = mapped_column(
        pg_enum(InvoiceStatus, "invoice_status"),
        nullable=False,
        default=InvoiceStatus.ISSUED,
    )
    # Состояние рендера PDF — вместо Redis-job (§10): PENDING → Celery,
    # READY/FAILED терминальные для одного прогона.
    pdf_status: Mapped[InvoicePdfStatus] = mapped_column(
        pg_enum(InvoicePdfStatus, "invoice_pdf_status"),
        nullable=False,
        default=InvoicePdfStatus.PENDING,
    )
    pdf_file_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Замороженная копия заказа (§16 п.40 п.3).
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Срок оплаты необязателен: в данных НБ РБ/УСН его нет (§16 п.40).
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Менеджер, выставивший счёт. SET NULL: удаление пользователя не должно
    # терять печатный документ из архива.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_invoices_order_id"),
        UniqueConstraint("seq", name="uq_invoices_seq"),
        UniqueConstraint("number", name="uq_invoices_number"),
        Index("ix_invoices_status", "status"),
    )


__all__ = ["Invoice", "invoices_seq_numbering"]
