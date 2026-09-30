"""Репозиторий уведомлений (in-app запись в notifications).

См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20, §16 п.39.

Состояние прочтения: личные уведомления — колонка ``Notification.is_read``;
broadcast (user_id IS NULL) — персонально, строкой в ``notification_reads``
(один read-факт на (notification, user)).
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.system import Notification, NotificationReadState


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


def _user_read_exists(user_id: uuid.UUID):
    """EXISTS-подзапрос «юзер уже прочитал это уведомление» (notification_reads)."""
    return exists(
        select(NotificationReadState.id).where(
            NotificationReadState.notification_id == Notification.id,
            NotificationReadState.user_id == user_id,
        )
    )


def _unread_condition(user):
    """«Непрочитано» для ленты — по-юзеру (§16 п.39).

    Личное: колонка is_read=false. Broadcast: read-строки юзера ещё нет.
    """
    return or_(
        and_(Notification.user_id == user.id, Notification.is_read.is_(False)),
        and_(Notification.user_id.is_(None), ~_user_read_exists(user.id)),
    )


def _apply_filters(stmt, *, user, type: str | None, unread_only: bool):
    if type:
        stmt = stmt.where(Notification.type == type)
    if unread_only:
        stmt = stmt.where(_unread_condition(user))
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
        user=user,
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
        user=user,
        type=type,
        unread_only=unread_only,
    )
    return int(await db.scalar(stmt) or 0)


async def fetch_read_broadcast_ids(
    db: AsyncSession, *, user_id: uuid.UUID, notification_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Какие из переданных broadcast-уведомлений юзер уже прочитал.

    Лента получает страницу строк и одним запросом дополняет broadcast
    персональным is_read (§16 п.39), вместо подзапроса на каждую строку.
    """
    if not notification_ids:
        return set()
    stmt = select(NotificationReadState.notification_id).where(
        NotificationReadState.user_id == user_id,
        NotificationReadState.notification_id.in_(notification_ids),
    )
    return set((await db.execute(stmt)).scalars().all())


async def count_unread_own(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Непрочитанные «свои» уведомления (бейдж колокольчика).

    Только user_id == текущему; broadcast в бейдж не попадает — осознанно
    (§16 п.39): иначе бейдж нельзя обнулить, не отметив чужие лиды.
    """
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user_id,
        Notification.is_read.is_(False),
    )
    return int(await db.scalar(stmt) or 0)


async def get_notification_for_user(db: AsyncSession, *, user, notification_id: uuid.UUID) -> Notification | None:
    """Уведомление, которое юзер имеет право отметить прочитанным (§16 п.39).

    Личное своё — да. Broadcast (user_id IS NULL) — да для менеджера (он видит
    его в ленте). Чужое личное / broadcast для не-менеджера — None (→ 404).
    """
    scope = Notification.id == notification_id
    if user.role == UserRole.MANAGER:
        scope = and_(scope, or_(Notification.user_id == user.id, Notification.user_id.is_(None)))
    else:
        scope = and_(scope, Notification.user_id == user.id)
    return await db.scalar(select(Notification).where(scope))


async def mark_read_broadcast(db: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """Записать персональное прочтение broadcast (идемпотентно).

    Возвращает True, если строка создана сейчас; False — уже была
    (ON CONFLICT DO NOTHING, повторный PATCH — не дубль и не ошибка).
    """
    res = await db.execute(
        postgres_insert(NotificationReadState)
        .values(id=uuid.uuid4(), notification_id=notification_id, user_id=user_id)
        .on_conflict_do_nothing(constraint="uq_notification_reads_notif_user")
    )
    return bool(res.rowcount)


async def mark_all_read(db: AsyncSession, *, user) -> int:
    """Отметить прочитанными всё непрочитанное из ленты юзера (§16 п.39).

    Личные — UPDATE is_read=true; broadcast (видимые менеджеру) — INSERT
    read-строк по ещё не прочитанным (ON CONFLICT DO NOTHING — идемпотентно
    при гонке повторных read-all). Возвращает суммарное число затронутых
    (обновлённые личные + новые read-строки). Коммитит вызывающий.
    """
    res = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    personal = res.rowcount or 0

    if user.role != UserRole.MANAGER:
        # Не-менеджер broadcast не видит: только личные (выше).
        return personal
    res = await db.execute(
        postgres_insert(NotificationReadState)
        .from_select(
            ["id", "notification_id", "user_id"],
            select(
                func.gen_random_uuid(),
                Notification.id,
                literal(user.id),
            ).where(
                Notification.user_id.is_(None),
                ~_user_read_exists(user.id),
            ),
        )
        .on_conflict_do_nothing(constraint="uq_notification_reads_notif_user")
    )
    return personal + (res.rowcount or 0)
