"""DTO in-app уведомлений (pull-лента). См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas import MetaPage


class NotificationRead(BaseModel):
    """Одно уведомление ленты.

    ``is_broadcast`` — уведомление всем менеджерам (user_id IS NULL): появляется
    в ленте менеджера, но «ничьё» — его нельзя отметить прочитанным.
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
    def from_notification(cls, notif) -> "NotificationRead":
        return cls(
            id=notif.id,
            type=notif.type,
            title=notif.title,
            body=notif.body,
            payload=notif.payload,
            is_read=notif.is_read,
            is_broadcast=notif.user_id is None,
            created_at=notif.created_at,
        )


class NotificationMeta(MetaPage):
    """MetaPage + счётчик непрочитанных «своих» уведомлений (бейдж колокольчика).

    unread_count считает только user_id == текущему пользователю; broadcast
    в бейдж не попадает (их нельзя отметить прочитанными).
    """
    unread_count: int = Field(ge=0)


class NotificationPage(BaseModel):
    data: list[NotificationRead]
    meta: NotificationMeta
