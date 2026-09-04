"""Роутер баннеров главной страницы (публичный). См. ARCHITECTURE_PLAN.md §6."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.enums import BannerPosition
from app.schemas.banner import BannerRead
from app.services.banner import BannerService

router = APIRouter(prefix="/banners", tags=["banners"])


@router.get("", response_model=list[BannerRead])
async def list_banners(
    position: BannerPosition | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[BannerRead]:
    """Активные баннеры (доступно без авторизации), sort ASC, created_at ASC."""
    return await BannerService(db).list_public(position)
