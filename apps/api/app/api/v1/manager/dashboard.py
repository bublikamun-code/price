"""Роутер дашборда менеджера (/api/v1/manager/dashboard). См. §6, §16 п.20-1 (фича G)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.manager_catalog import DashboardOut
from app.services.dashboard import DashboardService

router = APIRouter(tags=["manager:dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> DashboardOut:
    """Сводка: KPI, заказы по дням (30 дней), топы, последние заявки.

    Дневные бакеты и границы периодов — по календарю Europe/Minsk.
    Ответ кэшируется в Redis на 60 с (fail-open, без пагинации).
    """
    return await DashboardService(db).get()
