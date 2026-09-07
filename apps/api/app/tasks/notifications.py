"""Задачи рассылки уведомлений (Telegram + in-app).

См. ARCHITECTURE_PLAN.md §20 (Центр уведомлений).
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
import redis as redis_lib
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories import users as users_repo
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


# Идемпотентность dispatch (аудит 2026-09-06). Celery запущен с task_acks_late=True
# + task_reject_on_worker_lost=True, поэтому при потере воркера/visibility timeout
# задача доставляется повторно — без защиты создаются дубли in-app уведомлений.
# Ключ ``notif:dispatched:{version_id}`` (Redis SET NX, TTL 7 дней) берётся на время
# прогона: успешное завершение оставляет ключ → re-delivery получает
# already_dispatched; сбой освобождает ключ, чтобы autoretry/re-delivery могли
# выполнить dispatch заново (ключ ставится «на успех», частичный прогон не
# фиксируется как отправленный).
_DISPATCH_LOCK_TTL_SEC = 60 * 60 * 24 * 7  # 7 дней

_lock_client: redis_lib.Redis | None = None


def _get_lock_client() -> redis_lib.Redis:
    """Ленивый sync-клиент Redis для блокировок (sync-контекст Celery-воркера).

    Отдельный атрибут модуля — тесты подменяют ``_get_lock_client`` на фейк.
    """
    global _lock_client
    if _lock_client is None:
        _lock_client = redis_lib.Redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _lock_client


def _dispatch_lock_key(version_id: str) -> str:
    return f"notif:dispatched:{version_id}"


def _try_acquire_dispatch_lock(version_id: str, token: str) -> bool:
    """SET NX EX: True — этот прогон владеет dispatch; False — уже отправлен/в работе.

    Redis недоступен → fail-open (True): потеря уведомлений хуже их дубля.
    """
    try:
        acquired = _get_lock_client().set(
            _dispatch_lock_key(version_id), token, nx=True, ex=_DISPATCH_LOCK_TTL_SEC
        )
        return bool(acquired)
    except Exception as exc:
        log.warning(
            "price_changed.lock_unavailable", version_id=version_id, error=str(exc)
        )
        return True


def _release_dispatch_lock(version_id: str, token: str) -> None:
    """Освободить ключ после сбоя — только если он всё ещё наш (сравнение токена)."""
    try:
        client = _get_lock_client()
        key = _dispatch_lock_key(version_id)
        if client.get(key) == token:
            client.delete(key)
    except Exception as exc:
        log.warning(
            "price_changed.lock_release_failed", version_id=version_id, error=str(exc)
        )


@celery_app.task(
    bind=True,
    name="app.tasks.notifications.dispatch_price_changed",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def dispatch_price_changed(self, version_id: str) -> dict:
    """Диспетчер уведомлений об изменении цен после импорта (§20.4, §7.2 шаг 8).

    Идемпотентность: Redis SET NX ``notif:dispatched:{version_id}`` — повторная
    доставка (acks_late) не создаёт дублей. Сбой → ключ освобождается, autoretry
    (экспоненциальный backoff, до 3 попыток) повторяет dispatch.
    """
    vid = str(version_id)
    token = uuid.uuid4().hex
    if not _try_acquire_dispatch_lock(vid, token):
        log.info("price_changed.already_dispatched", version_id=vid)
        return {"status": "already_dispatched", "version_id": vid}
    try:
        return asyncio.run(_dispatch(uuid.UUID(vid)))
    except Exception as exc:
        _release_dispatch_lock(vid, token)
        log.exception(
            "price_changed.attempt_failed",
            version_id=vid,
            attempt=self.request.retries + 1,
            error=str(exc),
        )
        raise


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
    """Создаёт in-app записи + ставит TG-задачи (§20.3, §20.4).

    Менеджеру — сводка всегда (кроме вырожденного случая «нет изменений
    вовсе»): env-чат TELEGRAM_MANAGER_CHAT_ID плюс все менеджеры с привязанным
    Telegram (chat_id берётся одним запросом). Клиентам opt-in — персональный
    дайджест: in-app всегда, Telegram — если привязан telegram_id.
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
        # TG менеджерам (§20.1): отдельной Celery-задачей, чтобы не блокировать
        # БД. send_telegram определён в этом же модуле — по глобальному имени.
        # Env-чат сохраняется; дополнительно — все MANAGER с привязанным
        # Telegram (один запрос; дубликат chat_id env/привязки убираем set'ом).
        manager_chat_ids: set[str] = set()
        if settings.telegram_manager_chat_id:
            manager_chat_ids.add(settings.telegram_manager_chat_id)
        manager_chat_ids.update(
            str(tg_id) for tg_id in await users_repo.fetch_manager_telegram_ids(db)
        )
        for chat_id in sorted(manager_chat_ids):
            send_telegram.delay(chat_id, text)

    # Клиенты opt-in: PRICE_CHANGED_DIGEST (in-app + Telegram, если привязан).
    for recipient in recipients:
        digest_text = build_client_digest_text(recipient)
        tg_id = getattr(recipient, "telegram_id", None)
        channels = ["inapp"]
        if tg_id:
            channels.append("telegram")
        notif = await create_notification(
            db,
            type="PRICE_CHANGED_DIGEST",
            title="Изменились цены",
            body=digest_text,
            user_id=recipient.user_id,
            channel=channels,
            payload={
                "version_id": str(version_id),
                "affected": [
                    {"sku": a.sku, "category": a.category} for a in recipient.affected
                ],
            },
        )
        # SSE-событие клиенту (§16 п.26): персональный канал, fail-open.
        publish_notification(notification_payload(notif), user_id=recipient.user_id)
        if tg_id:
            send_telegram.delay(str(tg_id), digest_text)
