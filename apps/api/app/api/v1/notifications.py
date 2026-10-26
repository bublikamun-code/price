"""Pull-лента + SSE-стрим in-app уведомлений. См. ARCHITECTURE_PLAN.md §6 («Уведомления»), §20.2, §16 п.26, §16 п.39.

Лента: собственные уведомления + broadcast всем менеджерам (user_id IS NULL,
``is_broadcast=true``). Прочтение персональное: личное — колонка is_read;
broadcast менеджер отмечает для себя (строка в notification_reads, §16 п.39);
чужое личное → 404. Broadcast не попадает в meta.unread_count (бейдж).

SSE: GET /notifications/stream — долгоживущий text/event-stream; авторизация по
cookie на момент коннекта; доставка — Redis pub/sub (services/notification_events).
"""
import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import AsyncSessionLocal, get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.notifications import NotificationPage, NotificationRead
from app.services import notification_events
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
    """Отметить прочитанными всё из ленты: личные и broadcast (§16 п.39)."""
    await NotificationsFeedService(db).mark_all_read(current_user)
    await db.commit()
    return None


@router.patch("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    """Отметить прочитанным: личное своё — is_read; broadcast — per-user read-строка
    (§16 п.39); чужое личное → 404."""
    try:
        notif = await NotificationsFeedService(db).mark_read(current_user, notification_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    await db.commit()
    return notif


# ----------------------------- SSE-стрим (§16 п.26) -----------------------------

# Верхняя граница жизни одного SSE-соединения. Обрыв клиента за nginx'ом не
# всегда доходит до генератора (апстрим живёт, пока в него пишут heartbeat'ы),
# поэтому стрим завершается сам: EventSource переподключится по retry: 5000,
# а «зомби»-коннект перестаёт держать pubsub-клиент максимум через этот срок.
_STREAM_TTL_SECONDS = 30 * 60


async def _auth_user_shortlived(request: Request) -> User:
    """Аутентификация для SSE: сессия БД закрывается ДО старта генератора.

    Обычный Depends(get_db) живёт до завершения ответа, а SSE-ответ бесконечен:
    сессия висела бы «idle in transaction» весь стрим, а при незаметном обрыве
    клиента за nginx'ом — навсегда (аудит 25.10: ~30 навигаций GUI-обхода
    исчерпали пул 10+20, и API отдавал 500 на все запросы к БД). Пользователь
    возвращается detached — expire_on_commit=False, загруженные поля (id, role)
    доступны и после close сессии.
    """
    async with AsyncSessionLocal() as db:
        return await get_current_user(request, db)


@router.get("/stream")
async def stream_notifications(
    current_user: User = Depends(_auth_user_shortlived),
) -> StreamingResponse:
    """SSE-стрим уведомлений: свой канал + notif:broadcast для MANAGER.

    Авторизация по cookie/Bearer на момент коннекта (query-токен исключён —
    логи). Долгоживущий коннект переживает истечение access: при drop
    EventSource переподключается (retry), при 401 фронт уходит в pull.
    """

    return StreamingResponse(
        _notification_events(current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx не буферизует (см. infra/nginx)
        },
    )


async def _notification_events(user: User):
    """Генератор SSE: событие ``notification`` + heartbeat ``: ping`` (§16 п.26).

    Async-клиент pub/sub открывается на запрос и закрывается в finally
    (lifespan клиентов не держит). Sync-publish из задач и этот подписчик —
    разные клиенты одного Redis.
    """
    client = notification_events.create_pubsub_client()
    pubsub = client.pubsub()
    channels = [notification_events.user_channel(user.id)]
    if user.role == UserRole.MANAGER:
        channels.append(notification_events.BROADCAST_CHANNEL)
    try:
        await pubsub.subscribe(*channels)
        # reconnect-интервал EventSource (мс) — до входа в цикл ожидания
        yield "retry: 5000\n\n"
        deadline = time.monotonic() + _STREAM_TTL_SECONDS
        while time.monotonic() < deadline:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=notification_events.HEARTBEAT_SECONDS,
            )
            if message and message.get("type") == "message":
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"event: notification\ndata: {data}\n\n"
            else:
                # нет событий за интервал — heartbeat, чтобы коннект не рвался
                yield ": ping\n\n"
        # TTL истёк — тихо закрываем стрим; EventSource переподключится по
        # retry: 5000 (кадр выше), пользователь переподключения не замечает.
        return
    except asyncio.CancelledError:
        # disconnect клиента — тихо выходим (cleanup в finally)
        return
    finally:
        for closer in (pubsub.aclose, client.aclose):
            try:
                await closer()
            except Exception:  # noqa: S110 — cleanup не должен шуметь на disconnect
                pass
