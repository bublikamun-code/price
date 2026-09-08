"""Полный экспорт продукции (менеджер): все характеристики + ссылки на фото, CSV.

Job-стейт живёт в том же Redis-неймспейсе ``export:job:{job_id}``, что и у
``services/export.py`` — тот же TTL, те же fail-open обёртки чтения/записи;
статус опрашивается общим ``services.export.get_job``. Отличия стейта: поле
``type="products_full"`` (диагностика) и фиксированный ``format="csv"``.

Саму выгрузку собирает Celery-задача ``app.tasks.export_products_full``:
см. её docstring — колонки характеристик (объединение ключей attributes)
и «Фото N» со ссылками на публичный ``/public/photo``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.models.user import User
from app.services import export as export_service

log = get_logger("app.services.product_export")

# Статусы — те же, что у services/export.py (единый контракт job'а §16 п.16).
STATUS_QUEUED = export_service.STATUS_QUEUED
STATUS_RUNNING = export_service.STATUS_RUNNING
STATUS_DONE = export_service.STATUS_DONE
STATUS_FAILED = export_service.STATUS_FAILED

# Фасад общей Redis-механики: роутер и задача используют имя этого модуля
# (см. tasks/_common.mark_redis_job_failed — ждёт set_job_state/STATUS_FAILED
# на уровне модуля сервиса-владельца job'а).
set_job_state = export_service.set_job_state


async def start_full_export(*, user: User) -> str:
    """Создать job (QUEUED) и запустить Celery-задачу. Возвращает ``job_id``."""
    from app.tasks.export_products_full import run_full_export  # lazy: цикличность импортов

    job_id = uuid.uuid4()
    state: dict[str, Any] = {
        "job_id": str(job_id),
        "user_id": str(user.id),
        "type": "products_full",
        "format": "csv",
        "status": STATUS_QUEUED,
        "error": None,
        "s3_key": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await export_service.safe_set_job(job_id, state)
    run_full_export.delay(str(job_id), str(user.id))
    return str(job_id)


async def get_full_export_job(user_id, job_id) -> dict[str, Any] | None:
    """Стейт job'а для владельца (чужой/несуществующий → ``None`` → 404)."""
    return await export_service.get_job(user_id, job_id)
