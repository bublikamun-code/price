"""Notification events (Redis Pub/Sub + SSE). См. ARCHITECTURE_PLAN.md §16 п.26.

Разделение ролей:
  * публикация — ``publish_notification``: sync-клиент (ленивый синглетон по
    образцу ``_get_redis`` в services/telegram_auth.py). Вызовы приходят и из
    async-контекста FastAPI, и из Celery-задач (обёртка ``asyncio.run``), а
    PUBLISH — короткая операция, sync-вызов работает в обоих мирах;
  * подписка — SSE-генератор ``api/v1/notifications.py`` держит
    ``redis.asyncio``-клиент (``create_pubsub_client``).

Формат SSE-события (зафиксирован потребителем useNotifications.ts, бейдж):
  ``event: notification`` + ``data`` — JSON ``{id, type, title, body}``.
Каналы: ``notifications:user:{user_id}`` (персональный) и
``notifications:broadcast`` (менеджерам, user_id=None).

Публикация fail-open: Redis недоступен → warning в лог, создание уведомления
не ломается (лента остаётся источником правды, SSE — оптимизация доставки).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import redis as redis_lib

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.services.notification_events")

BROADCAST_CHANNEL = "notifications:broadcast"
HEARTBEAT_SECONDS = 30

_redis_client: redis_lib.Redis | None = None


def user_channel(user_id: uuid.UUID) -> str:
    """Канал SSE конкретного пользователя."""
    return f"notifications:user:{user_id}"


def notification_payload(notif) -> dict[str, Any]:
    """Payload SSE-события: тот же JSON ждёт фронтовый потребитель."""
    return {
        "id": str(notif.id) if hasattr(notif, "id") else "",
        # type может быть enum (NotificationType) или уже строкой (значение
        # колонки) — в обоих случаях отдаём строковое имя.
        "type": notif.type.value if hasattr(getattr(notif, "type", None), "value") else getattr(notif, "type", ""),
        "title": notif.title if hasattr(notif, "title") else "",
        "body": notif.body if hasattr(notif, "body") else "",
    }


def _get_redis() -> redis_lib.Redis:
    """Ленивый sync-клиент Redis — тесты подменяют ``_get_redis`` на фейк."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


def publish_notification(payload: dict[str, Any], user_id: uuid.UUID | None) -> None:
    """Опубликовать событие в Redis Pub/Sub (fail-open).

    ``user_id`` → персональный канал; ``None`` → broadcast всем менеджерам.
    Сбой брокера не роняет вызывающий код — без события SSE-клиент просто
    дождётся следующего poll/heartbeat, уведомление останется в ленте.
    """
    channel = user_channel(user_id) if user_id is not None else BROADCAST_CHANNEL
    try:
        # ensure_ascii=False: кириллица остаётся читаемой в Redis-логах;
        # переводы строк внутри значений json экранирует — SSE-кадр не рвётся.
        _get_redis().publish(channel, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        log.warning(
            "notifications.publish_failed", channel=channel, error=str(exc)
        )


def create_pubsub_client():
    """Redis-клиент для подписки SSE (redis.asyncio, без decode — данные
    приходят байтами, генератор декодирует сам)."""
    import redis.asyncio as redis
    return redis.from_url(settings.redis_url)
