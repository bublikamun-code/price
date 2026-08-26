"""Загрузка курсов валют НБ РБ (ежедневно по расписанию beat).

См. ARCHITECTURE_PLAN.md §17.1.
Источник: https://www.nbrb.by/api/exrates/rates?periodicity=0

Контракт:
  Вход:  нет (задача по cron beat).
  Шаги:
    1. GET {nbrb_rates_url}?periodicity=0 → JSON-массив курсов;
    2. фильтр по отслеживаемым валютам (settings.display_currency_list минус BYN);
    3. upsert в exchange_rates (source='NBRB') по uq_rates_currency_date_source;
    4. при недоступности НБ РБ — fallback: алёрт RATE_FETCH_FAILED менеджеру
       (in-app + telegram, §20.3), данные не перетираются (остаётся последний курс).

Идемпотентность: on_conflict_do_update → повторный прогон того же дня обновляет
rate/scale, не создавая дублей; слепой авто-ретрай отключён (autoretry_for=()).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.models.pricing import ExchangeRate
from app.repositories.notifications import create_notification
from app.services.notification_events import notification_payload, publish_notification
from app.workers import celery_app

log = get_logger("app.tasks.fetch_nbrb_rates")

# Отдельный движок для Celery-задач. NullPool принципиален: соединение asyncpg
# привязывается к event-loop'у, а задача крутится в своём asyncio.run на каждый
# вызов. Тесты подменяют ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_worker_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_worker_engine, expire_on_commit=False
)

# Курсы для отслеживания. BYN — базовая, её курс не нужен.
TRACKED = set(settings.display_currency_list) - {"BYN"}


@celery_app.task(
    bind=True, name="app.tasks.fetch_nbrb_rates.fetch_rates", autoretry_for=()
)
def fetch_rates(self) -> dict:
    """Sync-обёртка: запускает async-пайплайн, ловит критические ошибки."""
    try:
        return asyncio.run(_fetch_rates())
    except Exception as exc:  # непредвиденное — без слепого ретрая
        log.exception("nbrb_rates.crashed", error=str(exc))
        return {"status": "error", "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _fetch_rates() -> dict:
    """Скачать → upsert. При ошибке сети — fallback на последний курс + алёрт."""
    try:
        payload = await _fetch_nbrb_json()
    except Exception as exc:
        log.warning("nbrb_rates.fetch_failed", error=str(exc))
        await _fallback_alert()
        return {"status": "fallback", "error": str(exc)}
    saved = await _upsert_rates(payload)
    log.info("nbrb_rates.saved", count=saved)
    return {"status": "ok", "saved": saved}


async def _fetch_nbrb_json() -> list[dict]:
    """GET НБ РБ. Мок-хук для тестов (monkeypatch этой функции)."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(settings.nbrb_rates_url, params={"periodicity": 0})
        resp.raise_for_status()
        return resp.json()


async def _upsert_rates(payload: list[dict]) -> int:
    """Отфильтровать TRACKED → upsert по uq_rates_currency_date_source."""
    rows: list[dict] = []
    for item in payload:
        code = item.get("Cur_Abbreviation")
        if code not in TRACKED:
            continue
        rows.append(
            {
                "currency_code": code,
                "rate": item["Cur_OfficialRate"],
                "scale": item.get("Cur_Scale", 1),
                "fetched_at": _parse_date(item.get("Date")),
                "source": "NBRB",
            }
        )
    if not rows:
        return 0
    async with _worker_session() as db:
        for row in rows:
            stmt = pg_insert(ExchangeRate).values(**row)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_rates_currency_date_source",
                set_={"rate": stmt.excluded.rate, "scale": stmt.excluded.scale},
            )
            await db.execute(stmt)
        await db.commit()
    return len(rows)


async def _fallback_alert() -> None:
    """Алёрт менеджеру: in-app запись (всем менеджерам) + Telegram при конфиге."""
    last = await _latest_fetched_date()
    # Текст собирается из Jinja2-шаблона (§20.1) — единый источник формулировок.
    # Lazy-import, чтобы избежать циклического импорта между tasks-модулями.
    from app.services.notifications import build_rate_fetch_failed_text

    text = build_rate_fetch_failed_text(last)
    async with _worker_session() as db:
        notif = await create_notification(
            db,
            type="RATE_FETCH_FAILED",
            title="Курс НБ РБ недоступен",
            body=text,
            user_id=None,
            channel=["inapp", "telegram"],
        )
        # SSE-событие менеджерам (§16 п.26): broadcast, fail-open.
        publish_notification(notification_payload(notif), user_id=None)
        await db.commit()
    if settings.telegram_manager_chat_id:
        # lazy-import, чтобы избежать циклического импорта между tasks-модулями.
        from app.tasks.notifications import send_telegram

        send_telegram.delay(settings.telegram_manager_chat_id, text)


async def _latest_fetched_date() -> str | None:
    """Дата последнего успешного курса (для текста алёрта)."""
    async with _worker_session() as db:
        row = await db.scalar(
            select(ExchangeRate.fetched_at)
            .order_by(ExchangeRate.fetched_at.desc())
            .limit(1)
        )
        return row.isoformat() if row else None


def _parse_date(value) -> date:
    """ISO-datetime из ответа НБ РБ → date. Устойчив к None/мусору → date.today()."""
    if not value:
        return date.today()
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return date.today()
