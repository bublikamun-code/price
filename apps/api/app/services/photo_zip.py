"""Обработка ZIP с фото серий (§10, §16 п.17): job-стейт в Redis + S3 + dispatch.

Контракт:
  * ``start_photo_zip`` — залить ZIP стримингом в S3 ``tmp-uploads``
    (ключ ``photo-zip/{job_id}.zip``), создать job ``QUEUED`` (ключ
    ``photozip:job:{job_id}``, TTL 24 ч) и диспатчить Celery-задачу
    ``run_photo_zip``;
  * ``get_job``          — стейт job'а для его владельца (чужой/несуществующий
    → ``None``, роутер отдаёт 404);
  * ``set_job_state``    — частичное обновление стейта из задачи
    (``RUNNING`` → ``DONE``/``FAILED``).

Стейт живёт только в Redis — как у экспорта (§16 п.16): выгрузка/обработка
фото — эфемерные артефакты, 24-часового TTL достаточно. Redis-ошибки не роняют
API — fail-open по образцу ``services/cache.py`` (safe_get/safe_set + warning).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User
from app.services import storage
from app.tasks.photo_zip import run_photo_zip

log = get_logger("app.services.photo_zip")

JOB_TTL_SECONDS = 24 * 60 * 60  # стейт job'а живёт сутки (как у экспорта)

# Статусы job'а (§16 п.17): QUEUED (создан) → RUNNING (воркер взял) → DONE/FAILED.
STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

_redis = Redis.from_url(settings.redis_url, decode_responses=True)


def _job_key(job_id) -> str:
    return f"photozip:job:{job_id}"


async def start_photo_zip(*, user: User, upload: UploadFile) -> str:
    """Залить ZIP в MinIO, создать job (QUEUED) и запустить Celery-задачу.

    ZIP уже провалидирован роутером (расширение/content-type/magic-bytes/размер).
    Порядок: S3 → Redis → dispatch. При ``StorageError`` job не создаётся,
    роутер отдаёт 502.
    """
    job_id = uuid.uuid4()
    key = f"photo-zip/{job_id}.zip"
    await upload.seek(0)
    await run_in_threadpool(
        storage.upload_fileobj,
        settings.s3_bucket_tmp, key, upload.file,
        content_type="application/zip",
    )
    state = {
        "job_id": str(job_id),
        "user_id": str(user.id),
        "status": STATUS_QUEUED,
        "error": None,
        "files": 0,
        "matched": 0,
        "unmatched": 0,
        "errors": [],
        "created_at": datetime.now(UTC).isoformat(),
    }
    await safe_set_job(job_id, state)
    run_photo_zip.delay(str(job_id), str(user.id), key)
    return str(job_id)


async def get_job(user_id, job_id) -> dict[str, Any] | None:
    """Стейт job'а для владельца. ``None`` — нет ключа, Redis лежит или чужой."""
    state = await safe_get_job(job_id)
    if state is None or state.get("user_id") != str(user_id):
        return None
    return state


async def set_job_state(job_id, **fields: Any) -> None:
    """Частично обновить стейт (status/error/счётчики), TTL продлевается.

    Job пишет только воркер-владелец задачи, поэтому get→set без CAS достаточно.
    Нет ключа (Redis чистился) — молча no-op: состояние восстановить неоткуда.
    """
    state = await safe_get_job(job_id)
    if state is None:
        return
    state.update(fields)
    await safe_set_job(job_id, state)


# ----- fail-open обёртки (§4: Redis не должен валить загрузку фото) -----

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
        log.warning("photozip.job_get_failed", job_id=str(job_id), error=str(exc))
        return None


async def safe_set_job(job_id, state: dict[str, Any]) -> None:
    """Redis недоступен → стейт не сохраняется, но API продолжает работать."""
    try:
        await _redis.set(
            _job_key(job_id), json.dumps(state, ensure_ascii=False), ex=JOB_TTL_SECONDS
        )
    except Exception as exc:
        log.warning("photozip.job_set_failed", job_id=str(job_id), error=str(exc))
