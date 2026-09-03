"""Notification events (Redis Pub/Sub + SSE) — заглушка (501 Not Implemented)."""
from __future__ import annotations

import uuid
from typing import Any


BROADCAST_CHANNEL = "notifications:broadcast"
HEARTBEAT_SECONDS = 30


def user_channel(user_id: uuid.UUID) -> str:
    """Канал SSE для конкретного пользователя — заглушка."""
    return f"notifications:user:{user_id}"


def notification_payload(notif) -> dict[str, Any]:
    """Сформировать payload для SSE — заглушка."""
    return {
        "id": str(notif.id) if hasattr(notif, "id") else "",
        "type": notif.type.value if hasattr(notif, "type") else "",
        "title": notif.title if hasattr(notif, "title") else "",
        "body": notif.body if hasattr(notif, "body") else "",
    }


def publish_notification(payload: dict[str, Any], user_id: uuid.UUID | None) -> None:
    """Опубликовать событие в Redis Pub/Sub — заглушка (ничего не делает)."""
    pass


def create_pubsub_client():
    """Создать Redis-клиент для Pub/Sub — заглушка."""
    import redis.asyncio as redis
    from app.core.config import settings
    return redis.from_url(settings.redis_url)
