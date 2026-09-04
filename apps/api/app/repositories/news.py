"""Репозиторий новостей (публичная лента + админский CRUD)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import News


def _active_scope(stmt):
    """Активные новости, опубликованные не позже текущего момента."""
    now = datetime.now(tz=timezone.utc)
    return stmt.where(News.is_active.is_(True), News.published_at <= now)


async def fetch_news(
    db: AsyncSession,
    *,
    limit: int = 10,
    offset: int = 0,
) -> list[News]:
    """Список активных новостей, новые сверху."""
    stmt = (
        _active_scope(select(News))
        .order_by(News.published_at.desc(), News.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def count_news(db: AsyncSession) -> int:
    """Количество активных опубликованных новостей (для пагинации)."""
    stmt = _active_scope(select(func.count(News.id)))
    return int(await db.scalar(stmt) or 0)


async def get_active_by_id(db: AsyncSession, news_id: uuid.UUID) -> News | None:
    """Одна активная опубликованная новость (публичная полная статья)."""
    stmt = _active_scope(select(News)).where(News.id == news_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def fetch_news_all(
    db: AsyncSession, *, limit: int = 10, offset: int = 0
) -> list[News]:
    """Все новости (админка, включая скрытые), новые сверху."""
    stmt = (
        select(News)
        .order_by(News.published_at.desc(), News.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def count_news_all(db: AsyncSession) -> int:
    """Количество всех новостей (для пагинации админки)."""
    stmt = select(func.count(News.id))
    return int(await db.scalar(stmt) or 0)


async def get_by_id(db: AsyncSession, news_id: uuid.UUID) -> News | None:
    res = await db.execute(select(News).where(News.id == news_id))
    return res.scalar_one_or_none()


async def create(db: AsyncSession, **fields) -> News:
    news = News(**fields)
    db.add(news)
    await db.flush()
    await db.refresh(news)
    return news


async def delete(db: AsyncSession, news: News) -> None:
    await db.delete(news)
    await db.flush()
