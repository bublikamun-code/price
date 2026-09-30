"""DTO in-app уведомлений (pull-лента). См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2, §16 п.39."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas import MetaPage


class NotificationRead(BaseModel):
    """Одно уведомление ленты.

    ``is_broadcast`` — уведомление всем менеджерам (user_id IS NULL). Прочтение
    персональное (§16 п.39): у личных — колонка is_read, у broadcast — строка
    в notification_reads; сервис передаёт вычисленное значение через is_read.
    """
    id: uuid.UUID
    type: str
    title: str | None = None
    body: str | None = None
    payload: dict | None = None
    is_read: bool
    is_broadcast: bool
    created_at: datetime

    @classmethod
    def from_notification(cls, notif, *, is_read: bool | None = None) -> "NotificationRead":
        """is_read: по умолчанию колонка модели; для broadcast сервис передаёт per-user факт."""
        return cls(
            id=notif.id,
            type=notif.type,
            title=notif.title,
            body=notif.body,
            payload=notif.payload,
            is_read=notif.is_read if is_read is None else is_read,
            is_broadcast=notif.user_id is None,
            created_at=notif.created_at,
        )


class NotificationMeta(MetaPage):
    """MetaPage + счётчик непрочитанных «своих» уведомлений (бейдж колокольчика).

    unread_count считает только user_id == текущему пользователю; broadcast
    в бейдж не попадает — осознанно (§16 п.39): у broadcast нет общего
    «непрочитано», а бейдж по персональным read-строкам сделал бы невозможным
    его обнуление без чтения чужих лидов.
    """
    unread_count: int = Field(ge=0)


class NotificationPage(BaseModel):
    data: list[NotificationRead]
    meta: NotificationMeta
