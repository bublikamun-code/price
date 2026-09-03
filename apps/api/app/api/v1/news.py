"""Роутер новостей. См. ARCHITECTURE_PLAN.md §6."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.news import NewsPage
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
