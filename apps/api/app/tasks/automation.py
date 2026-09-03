"""Автоматизация (Celery). Заглушка."""
from __future__ import annotations

from app.workers import celery_app


@celery_app.task(bind=True, name="automation")
def run_automation(self, **kwargs) -> None:
    return None
