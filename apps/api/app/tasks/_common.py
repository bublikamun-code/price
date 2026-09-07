"""Общие утилиты для Celery-задач (движок задачи + FAILED-стейт в Redis)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


def create_worker_db():
    """Создать отдельный движок и сессию для Celery-задачи — заглушка."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )
    return engine, session


async def mark_redis_job_failed(service_module: str, job_id, message: str) -> None:
    """Пометить job FAILED в Redis сервиса-владельца job'а.

    Вызывается sync-обёрткой задачи (``run_export``/``run_photo_zip``), когда
    пайплайн упал после перехода в RUNNING: без этой записи job остаётся
    RUNNING до суточного TTL ключа, и клиент поллит впустую. Записываем тем же
    механизмом ``set_job_state``, которым пишутся RUNNING/DONE (fail-open
    обёртки внутри; нет ключа — no-op).

    ``service_module`` — строка вида ``"app.services.export"``: ленивый импорт
    через importlib, т.к. на уровне модуля получится цикл (сервис импортирует
    задачу, задача — этот модуль). У сервиса ждём константу ``STATUS_FAILED``.
    """
    import importlib

    service = importlib.import_module(service_module)
    await service.set_job_state(
        job_id, status=service.STATUS_FAILED, error=message
    )
