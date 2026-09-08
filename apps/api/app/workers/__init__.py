"""Celery app + конфигурация beat-расписания.

См. ARCHITECTURE_PLAN.md §7 (импорт CSV), §17 (курсы НБ РБ), §20 (уведомления),
§12 + §16 п.23 (метрики задач через Pushgateway).
"""
import time

import redis as redis_lib
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun, task_prerun

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    DEFAULT_QUEUE,
    push_beat_metrics,
    push_worker_metrics,
    record_task_duration,
    record_task_failure,
    set_queue_depth,
)

log = get_logger("app.workers")

celery_app = Celery(
    "price_portal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.import_price_list",
        "app.tasks.fetch_nbrb_rates",
        "app.tasks.notifications",
        "app.tasks.email",
        "app.tasks.export_catalog",
        "app.tasks.export_order_pdf",
        "app.tasks.export_products_full",
        "app.tasks.photo_zip",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Minsk",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Ретраи для transient-ошибок
    task_autoretry_for=(Exception,),
    task_max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    # Видимость результатов
    result_extended=True,
    task_time_limit=60 * 30,         # 30 минут hard
    task_soft_time_limit=60 * 25,    # 25 минут soft
)

# ---------- Beat-расписание ----------
celery_app.conf.beat_schedule = {
    # Ежедневная загрузка курсов НБ РБ (§17.1)
    "fetch-nbrb-rates-daily": {
        "task": "app.tasks.fetch_nbrb_rates.fetch_rates",
        "schedule": crontab(minute=5, hour=0),  # 00:05 Europe/Minsk
    },
    # Глубина очереди → Pushgateway каждые 30 с (§12, §16 п.23)
    "metrics-push-queue-depth": {
        "task": "app.workers.metrics_push_queue_depth",
        "schedule": 30.0,
    },
    # Reconciler зависших импортов: PROCESSING старше 6 ч → FAILED (§7.2).
    # Воркер умер → повторно доставленная задача уходит в «skipped», версию
    # иначе никто не переведёт из PROCESSING.
    "reconcile-stuck-imports": {
        "task": "app.tasks.import_price_list.reconcile_stuck_imports",
        "schedule": 900.0,  # каждые 15 минут
    },
}


@celery_app.task(bind=True, name="app.tasks.ping")
def ping(self) -> str:
    """Служебная задача для проверки живости воркера."""
    return "pong"


# ---------- Celery-метрики (§12, §16 п.23, Pushgateway-паттерн) ----------
_task_started: dict[str, float] = {}  # task_id → time.monotonic() старта

# Ленивый redis-клиент к broker-БД: глубина очереди читается через LLEN.
# Module-level для подмены в тестах (fakeredis).
_broker_redis: redis_lib.Redis | None = None


def _get_broker_redis() -> redis_lib.Redis:
    global _broker_redis
    if _broker_redis is None:
        _broker_redis = redis_lib.Redis.from_url(settings.celery_broker_url)
    return _broker_redis


@task_prerun.connect
def _on_task_prerun(task_id: str | None = None, **_kwargs) -> None:
    """Фиксируем старт задачи — длительность считаем в task_postrun."""
    if task_id is not None:
        _task_started[task_id] = time.monotonic()


@task_postrun.connect
def _on_task_postrun(
    task_id: str | None = None,
    task=None,
    state: str | None = None,
    **_kwargs,
) -> None:
    """После задачи: histogram длительности, counter окончательных провалов,
    push в Pushgateway (fail-open — см. app/core/metrics.py)."""
    started = _task_started.pop(task_id, None)
    task_name = getattr(task, "name", None) or "unknown"
    if started is not None:
        record_task_duration(task_name, time.monotonic() - started)
    if state == "FAILURE":  # окончательный провал (после всех ретраев)
        record_task_failure(task_name)
        log.warning("celery.task.failed", task=task_name)
    push_worker_metrics()


@celery_app.task(name="app.workers.metrics_push_queue_depth")
def metrics_push_queue_depth() -> dict:
    """Beat каждые 30 с: глубина дефолтной очереди (LLEN) → Pushgateway."""
    try:
        depth = int(_get_broker_redis().llen(DEFAULT_QUEUE))
    except Exception as exc:  # noqa: BLE001 — Redis недоступен: не роняем beat
        log.warning("celery.queue_depth.failed", queue=DEFAULT_QUEUE, error=str(exc))
        return {"status": "error", "error": str(exc)}
    set_queue_depth(DEFAULT_QUEUE, depth)
    push_beat_metrics()  # fail-open
    log.debug("celery.queue_depth", queue=DEFAULT_QUEUE, depth=depth)
    return {"status": "ok", "queue": DEFAULT_QUEUE, "depth": depth}
