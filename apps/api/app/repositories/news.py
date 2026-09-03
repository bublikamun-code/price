"""Репозиторий новостей (публичная лента)."""
from __future__ import annotations

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
