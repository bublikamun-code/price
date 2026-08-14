"""Репозиторий уведомлений (in-app запись в notifications).

См. ARCHITECTURE_PLAN.md §20.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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
