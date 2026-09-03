"""Общие утилиты для Celery-задач — заглушка (501 Not Implemented)."""
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


async def mark_redis_job_failed(service_module: str, job_id: str, message: str) -> None:
    """Пометить job как failed в Redis — заглушка (ничего не делает)."""
    pass
