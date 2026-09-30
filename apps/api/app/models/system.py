"""Системные таблицы: аудит и уведомления. См. ARCHITECTURE_PLAN.md §5, §20."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey


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
