"""Роутер новостей менеджера (/api/v1/manager/news). См. §6.

Админский CRUD новостей: список всех (включая скрытые), создание, частичное
обновление, удаление. Роль MANAGER (§11 RBAC).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.news import NewsCreate, NewsPage, NewsRead, NewsUpdate
from app.services.news import NewsService, NotFoundError

router = APIRouter(prefix="/news", tags=["manager:news"])


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, прочие ValueError → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("", response_model=NewsPage)
async def list_news_admin(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=200),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> NewsPage:
    """Все новости (включая is_active=False), published_at DESC."""
    return await NewsService(db).list_admin(page, per_page)


@router.post("", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
async def create_news(
    payload: NewsCreate,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> NewsRead:
    news = await NewsService(db).create(payload)
    await db.commit()
    return news


@router.patch("/{news_id}", response_model=NewsRead)
async def update_news(
    news_id: uuid.UUID,
    payload: NewsUpdate,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> NewsRead:
    try:
        news = await NewsService(db).update(news_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    await db.commit()
    return news


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news(
    news_id: uuid.UUID,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await NewsService(db).delete(news_id)
    except ValueError as exc:
        raise _to_http(exc) from exc
    await db.commit()
