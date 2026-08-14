"""Агрегирующий роутер менеджера (/api/v1/manager/**). См. §6.

Все эндпоинты защищены RBAC: role=MANAGER (см. ARCHITECTURE_PLAN.md §11).
Полная реализация — по этапам 8–10. Здесь — ping для проверки доступа.
"""
from fastapi import APIRouter, Depends

from app.api.v1.manager import orders, prices
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User

router = APIRouter(prefix="/manager", tags=["manager"])
router.include_router(prices.router)
router.include_router(orders.router)


@router.get("/ping")
async def ping(
    user: User = Depends(require_role(UserRole.MANAGER)),
) -> dict[str, str]:
    """Health/доступ для менеджера. Используется в тестах RBAC."""
    return {"pong": "ok", "manager": user.email}
