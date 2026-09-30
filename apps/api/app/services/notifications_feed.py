"""Сервис pull-ленты in-app уведомлений. См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2, §16 п.39.

Лента текущего пользователя: собственные уведомления + broadcast-уведомления
всем менеджерам (user_id IS NULL). Прочтение — персональное: у личных — колонка
``is_read``, у broadcast — строка в ``notification_reads`` на (уведомление, юзер).
Бейдж (``unread_count``) — осознанно только по личным.
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
        # Персональный is_read для broadcast на странице: один запрос вместо
        # подзапроса на строку (§16 п.39).
        broadcast_ids = [n.id for n in rows if n.user_id is None]
        read_broadcast = await notif_repo.fetch_read_broadcast_ids(
            self.db, user_id=user.id, notification_ids=broadcast_ids
        )
        unread_count = await notif_repo.count_unread_own(self.db, user_id=user.id)
        return NotificationPage(
            data=[
                NotificationRead.from_notification(
                    n,
                    is_read=n.is_read if n.user_id is not None else n.id in read_broadcast,
                )
                for n in rows
            ],
            meta=NotificationMeta(
                page=page, per_page=per_page, total=total, unread_count=unread_count
            ),
        )

    async def mark_read(self, user, notification_id: uuid.UUID) -> NotificationRead:
        """Отметить прочитанным (§16 п.39).

        Личное своё — колонка ``is_read``; broadcast — персональная read-строка
        (идемпотентно); чужое личное → ValueError (404).
        """
        notif = await notif_repo.get_notification_for_user(
            self.db, user=user, notification_id=notification_id
        )
        if notif is None:
            raise ValueError("Уведомление не найдено")
        if notif.user_id is None:
            await notif_repo.mark_read_broadcast(
                self.db, user_id=user.id, notification_id=notification_id
            )
            return NotificationRead.from_notification(notif, is_read=True)
        notif.is_read = True
        await self.db.flush()
        return NotificationRead.from_notification(notif)

    async def mark_all_read(self, user) -> int:
        """Отметить прочитанным всё из ленты юзера: личные + broadcast (§16 п.39). Коммитит роутер."""
        return await notif_repo.mark_all_read(self.db, user=user)
