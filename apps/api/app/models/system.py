"""Системные таблицы: аудит и уведомления. См. ARCHITECTURE_PLAN.md §5, §20."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey


class AuditLog(Base, UUIDPrimaryKey):
    """Журнал действий (mutation-операции менеджера). См. §5, §11."""
    __tablename__ = "audit_log"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. 'user.discount.update'
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_audit_actor_time", "actor_id", "created_at"),
        Index("ix_audit_action_time", "action", "created_at"),
    )


class Notification(Base, UUIDPrimaryKey):
    """In-app уведомления (колокольчик + SSE). См. §20.2."""
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )  # NULL → всем менеджерам
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    channel: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    is_read: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "ix_notif_user_unread",
            "user_id",
            postgresql_where=text("is_read = FALSE"),
        ),
        # Лента «новые сверху» (created_at DESC, id DESC) и фильтр по типу
        # уведомления. Частичный ix_notif_user_unread выше обслуживает только
        # счётчик непрочитанных и не покрывает ни порядок, ни тип.
        # Созданы миграцией 0025; объявлены в модели ради alembic check
        # (аудит 2026-09-06 §3).
        Index("ix_notifications_created", text("created_at DESC")),
        Index(
            "ix_notifications_type_created",
            "type",
            text("created_at DESC"),
        ),
    )


class NotificationReadState(Base, UUIDPrimaryKey):
    """Персональный факт прочтения broadcast-уведомления. См. §16 п.39.

    Колонка ``Notification.is_read`` — состояние только личных уведомлений
    (user_id задан). Broadcast (user_id IS NULL) виден всем менеджерам, поэтому
    «прочитано» для него — per-user: строка здесь = «юзер прочитал». Имя класса
    сознательно не ``NotificationRead`` — это имя Pydantic-DTO ленты.
    """
    __tablename__ = "notification_reads"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_notif_user"),
        Index("ix_notification_reads_user", "user_id"),
    )


class EmailOutbox(Base, TimestampMixin, UUIDPrimaryKey):
    """Durable-очередь исходящих писем (NOTIF-01). См. §5.2, §20.1.

    Зачем: раньше ``queue_email`` ставил задачу сразу в Celery-брокер — падение
    брокера между ответом HTTP и ``.delay()`` теряло письмо безвозвратно.
    Теперь письмо сначала фиксируется строкой PENDING (свой коммит, не зависит
    ни от HTTP-транзакции, ни от брокера), затем диспетчится задача. Свипер
    (beat) периодически реэнквитит зависшие PENDING — «потерянных» писем нет.

    Идемпотентность задачи: статус SENT проверяется перед отправкой (acks_late
    пере-доставка не шлёт повторно); ``dedupe_key`` (UNIQUE, nullable — NULL не
    конфликтует) отсекает дубли на уровне постановки.

    Статусы — свободные строки (как ``Notification.type``): PL/PG-enum дал бы
    миграцию на каждое новое состояние ради 4 значений. ``SKIPPED`` — отдельный
    терминальный статус «SMTP не сконфигурирован»: это не ошибка письма (FAILED
    ввёл бы в заблуждение алёрты) и не PENDING (свипер гонял бы его вечно).
    """
    __tablename__ = "email_outbox"

    STATUS_PENDING = "PENDING"    # в очереди: ждёт задачу / повтор после сбоя
    STATUS_SENT = "SENT"          # отправлено (терминальный)
    STATUS_FAILED = "FAILED"      # ретраи исчерпаны (терминальный; см. свипер)
    STATUS_SKIPPED = "SKIPPED"    # нет SMTP-транспорта (терминальный, dev/test)

    to: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, server_default=STATUS_PENDING
    )
    # Число SMTP-попыток (инкремент в начале каждой попытки — попытка,
    # прерванная смертью воркера, тоже должна быть видна).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # UNIQUE, а не обычный индекс: ON CONFLICT (dedupe_key) DO NOTHING —
        # конкурентная постановка с тем же ключом даёт ровно одну строку.
        Index("uq_email_outbox_dedupe_key", "dedupe_key", unique=True),
    )
