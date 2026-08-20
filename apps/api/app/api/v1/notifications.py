"""Pull-лента in-app уведомлений (колокольчик). См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2.

Лента: собственные уведомления + broadcast всем менеджерам (user_id IS NULL,
``is_broadcast=true``). Отметить прочитанным можно только своё — чужое/broadcast → 404;
broadcast не попадает в meta.unread_count (бейдж).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notifications import NotificationPage, NotificationRead
from app.services.notifications_feed import NotificationsFeedService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    type: str | None = Query(default=None, max_length=64),
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPage:
    """Лента уведомлений текущего пользователя (новые сверху)."""
    return await NotificationsFeedService(db).list(
        current_user, type=type, unread_only=unread_only, page=page, per_page=per_page
    )


# ВАЖНО: /read-all объявляется до параметризованных маршрутов, чтобы не был
# перекрыт путем /{notification_id}/... (порядок регистрации маршрутов в FastAPI).
@router.patch("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Отметить прочитанными все СВОИ непрочитанные уведомления (broadcast не трогаем)."""
    await NotificationsFeedService(db).mark_all_read(current_user)
    await db.commit()
    return None


@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    """Отметить уведомление прочитанным (только своё; чужое/broadcast → 404)."""
    try:
        notif = await NotificationsFeedService(db).mark_read(current_user, notification_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    await db.commit()
    return notif
