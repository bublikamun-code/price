"""Email-уведомления (Celery). Заглушка."""
from __future__ import annotations

from app.workers import celery_app


@celery_app.task(bind=True, name="email")
def send_email(self, **kwargs) -> None:
    return None
