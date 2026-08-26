"""Задачи рассылки уведомлений (Telegram + in-app).

См. ARCHITECTURE_PLAN.md §20 (Центр уведомлений).
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.notifications import create_notification
from app.services.notification_events import notification_payload, publish_notification
from app.services.notifications import (
    build_client_digest_text,
    build_manager_price_changed_text,
)
from app.services.price_changes import (
    DigestRecipient,
    VersionDiff,
    compute_version_diff,
    find_digest_recipients,
)
from app.workers import celery_app

log = get_logger("app.tasks.notifications")

TG_API_BASE = "https://api.telegram.org"

# Отдельный движок для Celery-задач. NullPool принципиален: соединение asyncpg
# привязывается к event-loop'у, а задача крутится в своём asyncio.run на каждый
# вызов (см. app/tasks/import_price_list.py). Тесты подменяют ``_worker_session``.
_worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_worker_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_worker_engine, expire_on_commit=False
)


@celery_app.task(bind=True, name="app.tasks.notifications.send_telegram")
def send_telegram(self, chat_id: str, text: str) -> dict:
    """Отправка сообщения в Telegram через Bot API (без parse_mode).

    Если бот не сконфигурирован или ``chat_id`` пуст — no-op (disabled).
    Сетевые ошибки пробрасываются — глобальный ``task_autoretry_for`` ретраит.
    """
    if not settings.telegram_bot_token or not chat_id:
        log.warning("tg.disabled")
        return {"status": "disabled"}
    try:
        return asyncio.run(_send_telegram(chat_id, text))
    except Exception as exc:
        log.warning("tg.send_failed", chat_id=chat_id, error=str(exc))
        raise


async def _send_telegram(chat_id: str, text: str) -> dict:
    """POST /bot{token}/sendMessage. Мок-хук для тестов (monkeypatch этой функции)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{TG_API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        resp.raise_for_status()
        return {"status": "ok", "chat_id": chat_id}


@celery_app.task(
    bind=True, name="app.tasks.notifications.dispatch_price_changed", autoretry_for=()
)
def dispatch_price_changed(self, version_id: str) -> dict:
    """Диспетчер уведомлений об изменении цен после импорта (§20.4, §7.2 шаг 8).

    Защита от двойного прогона не делается — вызов из import_price_list однократный,
    autoretry отключён (``autoretry_for=()``).
    """
    try:
        return asyncio.run(_dispatch(uuid.UUID(version_id)))
    except Exception as exc:
        log.exception(
            "price_changed.crashed", version_id=str(version_id), error=str(exc)
        )
        return {"status": "error", "version_id": str(version_id), "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _dispatch(version_id: uuid.UUID) -> dict:
    """Сравнить версии → посчитать diff → менеджеру + клиентам opt-in (§20.4)."""
    async with _worker_session() as db:
        diff = await compute_version_diff(db, version_id)
        recipients = (
            await find_digest_recipients(db, diff.changed) if diff.changed else []
        )
        await _notify(db, version_id, diff, recipients)
        await db.commit()

    log.info(
        "price_changed.dispatched",
        version_id=str(version_id),
        count_up=diff.count_up,
        count_down=diff.count_down,
        count_new=diff.count_new,
        count_override_reset=diff.count_override_reset,
        count_unchanged=diff.count_unchanged,
        recipients=len(recipients),
    )
    return {
        "status": "ok",
        "version_id": str(version_id),
        "counts": {
            "up": diff.count_up,
            "down": diff.count_down,
            "new": diff.count_new,
            "override_reset": diff.count_override_reset,
            "unchanged": diff.count_unchanged,
        },
        "recipients": len(recipients),
    }


async def _notify(
    db: AsyncSession,
    version_id: uuid.UUID,
    diff: VersionDiff,
    recipients: list[DigestRecipient],
) -> None:
    """Создаёт in-app записи + ставит TG-задачу менеджеру (§20.3, §20.4).

    Менеджеру — сводка всегда, кроме вырожденного случая «нет изменений вовсе»
    (``changed`` пуст и ``count_new == 0``). Клиентам opt-in — индивидуальный
    дайджест по изменившимся позициям (только in-app; TG клиентам отложен, §20).
    """
    # Менеджер: PRICE_CHANGED (всем менеджерам, user_id=None).
    if diff.changed:
        text = build_manager_price_changed_text(diff)
        notif = await create_notification(
            db,
            type="PRICE_CHANGED",
            title="Прайс-лист обновлён",
            body=text,
            user_id=None,
            channel=["inapp", "telegram"],
            payload={
                "version_id": str(version_id),
                "count_up": diff.count_up,
                "count_down": diff.count_down,
                "count_new": diff.count_new,
                "count_override_reset": diff.count_override_reset,
                "count_unchanged": diff.count_unchanged,
            },
        )
        # SSE-событие менеджерам (§16 п.26): broadcast, fail-open.
        publish_notification(notification_payload(notif), user_id=None)
        # TG менеджеру (§20.1): отдельной Celery-задачей, чтобы не блокировать БД.
        # send_telegram определён в этом же модуле — обращение по глобальному имени.
        if settings.telegram_manager_chat_id:
            send_telegram.delay(settings.telegram_manager_chat_id, text)

    # Клиенты opt-in: PRICE_CHANGED_DIGEST (in-app, персонально).
    for recipient in recipients:
        digest_text = build_client_digest_text(recipient)
        notif = await create_notification(
            db,
            type="PRICE_CHANGED_DIGEST",
            title="Изменились цены",
            body=digest_text,
            user_id=recipient.user_id,
            channel=["inapp"],
            payload={
                "version_id": str(version_id),
                "affected": [
                    {"sku": a.sku, "category": a.category} for a in recipient.affected
                ],
            },
        )
        # SSE-событие клиенту (§16 п.26): персональный канал, fail-open.
        publish_notification(notification_payload(notif), user_id=recipient.user_id)
