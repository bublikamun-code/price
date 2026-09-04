"""Репозиторий баннеров главной страницы."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banner import Banner
from app.models.enums import BannerPosition


async def fetch_active(
    db: AsyncSession, *, position: BannerPosition | None = None
) -> list[Banner]:
    """Активные баннеры (публичная выдача): sort ASC, created_at ASC."""
    stmt = select(Banner).where(Banner.is_active.is_(True))
    if position is not None:
        stmt = stmt.where(Banner.position == position)
    stmt = stmt.order_by(Banner.sort.asc(), Banner.created_at.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def fetch_all(db: AsyncSession) -> list[Banner]:
    """Все баннеры (админка, включая скрытые): position, sort."""
    stmt = select(Banner).order_by(Banner.position.asc(), Banner.sort.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_by_id(db: AsyncSession, banner_id: uuid.UUID) -> Banner | None:
    res = await db.execute(select(Banner).where(Banner.id == banner_id))
    return res.scalar_one_or_none()


async def create(db: AsyncSession, **fields) -> Banner:
    banner = Banner(**fields)
    db.add(banner)
    await db.flush()
    await db.refresh(banner)
    return banner


async def update(db: AsyncSession, banner: Banner, **fields) -> Banner:
    for key, value in fields.items():
        setattr(banner, key, value)
    await db.flush()
    await db.refresh(banner)
    return banner


async def delete(db: AsyncSession, banner: Banner) -> None:
    await db.delete(banner)
    await db.flush()
