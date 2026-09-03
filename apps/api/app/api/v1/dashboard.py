"""Роутер клиентского дашборда (/api/v1/dashboard). См. §6, §16 п.20.

Экран «Моя аналитика» (SITEMAP /dashboard): сводка по данным ТЕКУЩЕГО
пользователя. Доступен любой авторизованной роли (аналогично менеджерскому
дашборду наоборот: скооп — user_id, а не роль). Ответ кэшируется в Redis
на 60 с (fail-open).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import ClientDashboardOut
from app.services.client_dashboard import ClientDashboardService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=ClientDashboardOut)
async def get_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClientDashboardOut:
    """Сводка по данным текущего пользователя: KPI (без CANCELLED), заявки
    по дням (30 дней), статусы, топ-5 товаров, последние/активные заявки,
    изменения цен в избранном, новинки, быстрые действия.

    Дневные бакеты и границы периодов — по календарю Europe/Minsk.
    Ответ кэшируется в Redis на 60 с (fail-open).
    """
    return await ClientDashboardService(db, user).get()
