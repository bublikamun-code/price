"""Агрегирующий роутер менеджера (/api/v1/manager/**). См. §6.

Все эндпоинты защищены RBAC: role=MANAGER (см. ARCHITECTURE_PLAN.md §11).
"""
from fastapi import APIRouter, Depends

from app.api.v1.manager import audit, currencies, files, orders, prices, users
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User

router = APIRouter(prefix="/manager", tags=["manager"])
router.include_router(prices.router)
router.include_router(orders.router)
router.include_router(files.router)
router.include_router(users.router)
router.include_router(currencies.router)
router.include_router(audit.router)


@router.get("/ping")
async def ping(
    user: User = Depends(require_role(UserRole.MANAGER)),
) -> dict[str, str]:
    """Health/доступ для менеджера. Используется в тестах RBAC."""
    return {"pong": "ok", "manager": user.email}
