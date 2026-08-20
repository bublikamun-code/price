"""Репозиторий уведомлений (in-app запись в notifications).

См. ARCHITECTURE_PLAN.md §20.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.system import Notification


async def create_notification(
    db: AsyncSession,
    *,
    type: str,
    title: str | None = None,
    body: str | None = None,
    user_id: uuid.UUID | None = None,  # None → всем менеджерам (§20)
    channel: list[str] | None = None,
    payload: dict | None = None,
) -> Notification:
    """Создать запись in-app уведомления. Коммитит вызывающий.

    Стиль как в ``repositories/catalog.py``: ``flush`` здесь, ``commit`` — в задаче.
    """
    notif = Notification(
        type=type,
        title=title,
        body=body,
        user_id=user_id,
        channel=channel,
        payload=payload,
    )
    db.add(notif)
    await db.flush()
    return notif


# ---------- pull-лента (§6 «Уведомления») ----------

def _feed_scope(user):
    """Лента текущего пользователя: свои уведомления + broadcast всем менеджерам.

    Broadcast (user_id IS NULL) виден только менеджерам.
    """
    own = Notification.user_id == user.id
    if user.role == UserRole.MANAGER:
        return or_(own, Notification.user_id.is_(None))
    return own


def _apply_filters(stmt, *, type: str | None, unread_only: bool):
    if type:
        stmt = stmt.where(Notification.type == type)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return stmt


async def fetch_notifications(
    db: AsyncSession,
    *,
    user,
    type: str | None = None,
    unread_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[Notification]:
    """Лента уведомлений (новые сверху: created_at DESC, id DESC)."""
    stmt = _apply_filters(
        select(Notification).where(_feed_scope(user)),
        type=type,
        unread_only=unread_only,
    ).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def count_notifications(
    db: AsyncSession,
    *,
    user,
    type: str | None = None,
    unread_only: bool = False,
) -> int:
    """Всего записей ленты под текущие фильтры (для пагинации)."""
    stmt = _apply_filters(
        select(func.count(Notification.id)).where(_feed_scope(user)),
        type=type,
        unread_only=unread_only,
    )
    return int(await db.scalar(stmt) or 0)


async def count_unread_own(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Непрочитанные «свои» уведомления (бейдж колокольчика).

    Только user_id == текущему; broadcast — «ничьи», в бейдж не попадают.
    """
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
    )
    return int(await db.scalar(stmt) or 0)


async def get_own_notification(
    db: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification | None:
    """Уведомление по id, только если оно адресовано пользователю.

    Broadcast (user_id IS NULL) и чужие записи не возвращаются.
    """
    return await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )


async def mark_all_read(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Отметить прочитанными все непрочитанные «свои» уведомления.

    Broadcast не трогаем (они ничьи). Возвращает число обновлённых записей.
    Коммитит вызывающий.
    """
    res = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    return res.rowcount or 0
