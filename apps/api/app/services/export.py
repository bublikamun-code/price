"""Экспорт каталога в CSV/XLSX (§16 п.16): job-стейт в Redis + dispatch Celery.

Контракт:
  * ``start_export`` — создать job ``QUEUED`` (ключ ``export:job:{job_id}``,
    TTL 24 ч) и диспатчить Celery-задачу ``run_export``;
  * ``get_job``      — стейт job'а для его владельца (чужой/несуществующий →
    ``None``, роутер отдаёт 404);
  * ``set_job_state``— частичное обновление стейта из задачи
    (``RUNNING`` → ``DONE``/``FAILED``).

Стейт живёт только в Redis (без строки в БД): выгрузка — эфемерный артефакт,
24-часового TTL достаточно; файлы в S3 ``csv-exports`` переживают ключ, но
presigned-ссылки живут 5 минут. Redis-ошибки не роняют API — fail-open
по образцу ``services/cache.py`` (safe_get/safe_set + log.warning).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.catalog import CatalogFilters
from app.tasks.export_catalog import run_export

log = get_logger("app.services.export")

JOB_TTL_SECONDS = 24 * 60 * 60  # стейт job'а живёт сутки (§16 п.16)

# Статусы job'а (§6): QUEUED (создан) → RUNNING (воркер взял) → DONE/FAILED.
STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

_redis = Redis.from_url(settings.redis_url, decode_responses=True)


def _job_key(job_id) -> str:
    return f"export:job:{job_id}"


def _filters_to_json(filters: CatalogFilters) -> str:
    """Фильтры каталога → JSON для аргументов Celery-задачи (uuid → str)."""
    return json.dumps(
        {
            "q": filters.q,
            "brand_ids": [str(b) for b in (filters.brand_ids or [])],
            "series_ids": [str(s) for s in (filters.series_ids or [])],
            "stock": filters.stock.value if filters.stock else None,
        },
        ensure_ascii=False,
    )


async def start_export(
    *,
    user: User,
    filters: CatalogFilters,
    format: str,
    price_calc_mode: str,
) -> str:
    """Создать job (QUEUED) и запустить Celery-задачу. Возвращает ``job_id``.

    ``format`` уже провалидирован роутером (csv|xlsx).
    """
    job_id = uuid.uuid4()
    state = {
        "job_id": str(job_id),
        "user_id": str(user.id),
        "format": format,
        "status": STATUS_QUEUED,
        "error": None,
        "s3_key": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await safe_set_job(job_id, state)
    run_export.delay(str(job_id), str(user.id), _filters_to_json(filters),
                     format, price_calc_mode)
    return str(job_id)


async def get_job(user_id, job_id) -> dict[str, Any] | None:
    """Стейт job'а для владельца. ``None`` — нет ключа, Redis лежит или чужой."""
    state = await safe_get_job(job_id)
    if state is None or state.get("user_id") != str(user_id):
        return None
    return state


async def set_job_state(job_id, **fields: Any) -> None:
    """Частично обновить стейт (status/s3_key/error), TTL продлевается.

    Job пишет только воркер-владелец задачи, поэтому get→set без CAS достаточно.
    Нет ключа (Redis чистился) — молча no-op: состояние восстановить неоткуда.
    """
    state = await safe_get_job(job_id)
    if state is None:
        return
    state.update(fields)
    await safe_set_job(job_id, state)


# ----- fail-open обёртки (§4: Redis не должен валить экспорт/каталог) -----

async def safe_get_job(job_id) -> dict[str, Any] | None:
    """Redis недоступен → «job не найден» (роутер отдаст 404)."""
    try:
        raw = await _redis.get(_job_key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        log.warning("export.job_get_failed", job_id=str(job_id), error=str(exc))
        return None


async def safe_set_job(job_id, state: dict[str, Any]) -> None:
    """Redis недоступен → стейт не сохраняется, но API продолжает работать."""
    try:
        await _redis.set(
            _job_key(job_id), json.dumps(state, ensure_ascii=False), ex=JOB_TTL_SECONDS
        )
    except Exception as exc:
        log.warning("export.job_set_failed", job_id=str(job_id), error=str(exc))
