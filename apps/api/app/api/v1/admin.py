"""Admin API — администрирование (/api/v1/admin). См. §6, §11 RBAC.

Управление менеджерами: список, создание с temp-паролем (паттерн §16 п.19),
блокировка/разблокировка и правка профиля. Доступ — только роль ADMIN.

Контракт повторяет apps/web/pages/manager/admin.vue 1-в-1:
  * GET   /admin/managers       → плоский list[AdminManagerOut] (страница
    рендерит таблицу целиком, без пагинации — конверт {data, meta} не используется);
  * POST  /admin/managers       → 201 {user, temp_password} (пароль показывается один раз);
  * PATCH /admin/managers/{id}  → AdminManagerOut (is_active / full_name / phone).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.admin import (
    AdminManagerCreateOut,
    AdminManagerIn,
    AdminManagerOut,
    AdminManagerPatchIn,
)
from app.services.admin_users import AdminUsersService, ConflictError, NotFoundError

router = APIRouter(prefix="/admin", tags=["admin"])


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, ConflictError → 409, прочие ValueError (валидация) → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/managers", response_model=list[AdminManagerOut])
async def list_managers(
    _admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> list[AdminManagerOut]:
    """Список менеджеров (плоский массив, без пагинации — контракт фронта)."""
    return await AdminUsersService(db).list_managers()


@router.post(
    "/managers",
    response_model=AdminManagerCreateOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_manager(
    payload: AdminManagerIn,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> AdminManagerCreateOut:
    """Создать менеджера; temp-пароль генерируется и показывается один раз."""
    service = AdminUsersService(db)
    try:
        user, temp_password = await service.create_manager(admin, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return AdminManagerCreateOut(user=service.to_out(user), temp_password=temp_password)


@router.patch("/managers/{manager_id}", response_model=AdminManagerOut)
async def update_manager(
    manager_id: uuid.UUID,
    payload: AdminManagerPatchIn,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> AdminManagerOut:
    """Правка профиля и/или блокировка/разблокировка (блокировка отзывает сессии)."""
    service = AdminUsersService(db)
    try:
        user = await service.update_manager(admin, manager_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return service.to_out(user)
