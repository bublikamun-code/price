"""Сервис pull-ленты in-app уведомлений. См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2.

Лента текущего пользователя: собственные уведомления + broadcast-уведомления
всем менеджерам (user_id IS NULL). Broadcast — «ничьи»: их нельзя отметить
прочитанными, и они не попадают в unread_count (бейдж колокольчика).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import notifications as notif_repo
from app.schemas.notifications import NotificationMeta, NotificationPage, NotificationRead


class NotificationsFeedService:
    """Операции с pull-лентой уведомлений текущего пользователя."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(
        self,
        user,
        *,
        type: str | None = None,
        unread_only: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> NotificationPage:
        limit, offset = per_page, (page - 1) * per_page
        rows = await notif_repo.fetch_notifications(
            self.db, user=user, type=type, unread_only=unread_only, limit=limit, offset=offset
        )
        total = await notif_repo.count_notifications(
            self.db, user=user, type=type, unread_only=unread_only
        )
        unread_count = await notif_repo.count_unread_own(self.db, user_id=user.id)
        return NotificationPage(
            data=[NotificationRead.from_notification(n) for n in rows],
            meta=NotificationMeta(
                page=page, per_page=per_page, total=total, unread_count=unread_count
            ),
        )

    async def mark_read(self, user, notification_id: uuid.UUID) -> NotificationRead:
        """Отметить своё уведомление прочитанным; чужое/broadcast → ValueError (404)."""
        notif = await notif_repo.get_own_notification(
            self.db, user_id=user.id, notification_id=notification_id
        )
        if notif is None:
            raise ValueError("Уведомление не найдено")
        notif.is_read = True
        await self.db.flush()
        return NotificationRead.from_notification(notif)

    async def mark_all_read(self, user) -> int:
        """Отметить прочитанными все свои непрочитанные уведомления. Коммитит роутер."""
        return await notif_repo.mark_all_read(self.db, user_id=user.id)
