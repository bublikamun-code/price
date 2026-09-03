"""Генерация PDF заказа (Celery). Заглушка."""
from __future__ import annotations

from app.workers import celery_app


@celery_app.task(bind=True, name="export_order_pdf", autoretry_for=())
def run_export_order_pdf(self, order_id: str, **kwargs) -> dict:
    return {"order_id": order_id, "status": "NOT_IMPLEMENTED"}
