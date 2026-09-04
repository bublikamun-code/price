"""Роутер новостей. См. ARCHITECTURE_PLAN.md §6."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.news import NewsPage, NewsRead
from app.services.news import NewsService

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=NewsPage)
async def list_news(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> NewsPage:
    """Публичная лента новостей (доступна без авторизации)."""
    return await NewsService(db).list(page, per_page)


@router.get("/{news_id}", response_model=NewsRead)
async def get_news(
    news_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> NewsRead:
    """Полная статья: только активные и уже опубликованные (иначе 404)."""
    try:
        return await NewsService(db).get_public(news_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
