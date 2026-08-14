"""Celery app + конфигурация beat-расписания.

См. ARCHITECTURE_PLAN.md §7 (импорт CSV), §17 (курсы НБ РБ), §20 (уведомления).
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "price_portal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.import_price_list",
        "app.tasks.fetch_nbrb_rates",
        "app.tasks.notifications",
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
}


@celery_app.task(bind=True, name="app.tasks.ping")
def ping(self) -> str:
    """Служебная задача для проверки живости воркера."""
    return "pong"
