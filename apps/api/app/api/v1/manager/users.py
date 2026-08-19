"""Роутер клиентов менеджера (/api/v1/manager/users). См. §6, §16 п.19.

Создание клиентов с temp-паролем, профиль, матрица скидок, фикс-курс.
Все эндпоинты требуют роль MANAGER (§11 RBAC); мутации пишут audit_log.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas import MetaPage
from app.schemas.manager_users import (
    ClientCreateIn,
    ClientCreateOut,
    DiscountsIn,
    DiscountOut,
    FixedRateIn,
    TempPasswordOut,
    UserPatchIn,
    UserManagerDetail,
    UserManagerPage,
    UserManagerRead,
)
from app.services.manager_users import (
    ConflictError,
    ManagerUsersService,
    NotFoundError,
)

router = APIRouter(prefix="/users", tags=["manager:users"])


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, ConflictError → 409, прочие ValueError (валидация) → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post("", response_model=ClientCreateOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreateIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ClientCreateOut:
    service = ManagerUsersService(db)
    try:
        user, temp_password = await service.create_client(manager, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return ClientCreateOut(user=await service.to_read(user), temp_password=temp_password)


@router.get("", response_model=UserManagerPage)
async def list_users(
    q: str | None = Query(default=None, description="Поиск: email/ФИО/компания"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> UserManagerPage:
    items, total = await ManagerUsersService(db).list_users(q=q, page=page, per_page=per_page)
    return UserManagerPage(data=items, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.get("/{user_id}", response_model=UserManagerDetail)
async def get_user(
    user_id: uuid.UUID,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> UserManagerDetail:
    service = ManagerUsersService(db)
    try:
        user, discounts = await service.get_detail(user_id)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return UserManagerDetail(user=await service.to_read(user), discounts=discounts)


@router.patch("/{user_id}", response_model=UserManagerRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserPatchIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> UserManagerRead:
    service = ManagerUsersService(db)
    try:
        user = await service.update_client(manager, user_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return await service.to_read(user)


@router.post("/{user_id}/reset-password", response_model=TempPasswordOut)
async def reset_password(
    user_id: uuid.UUID,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> TempPasswordOut:
    service = ManagerUsersService(db)
    try:
        _, temp_password = await service.reset_password(manager, user_id)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return TempPasswordOut(temp_password=temp_password)


@router.put("/{user_id}/discounts", response_model=list[DiscountOut])
async def set_discounts(
    user_id: uuid.UUID,
    payload: DiscountsIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> list[DiscountOut]:
    service = ManagerUsersService(db)
    try:
        return await service.set_discounts(manager, user_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.put("/{user_id}/fixed-rate", response_model=UserManagerRead)
async def set_fixed_rate(
    user_id: uuid.UUID,
    payload: FixedRateIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> UserManagerRead:
    service = ManagerUsersService(db)
    try:
        user = await service.set_fixed_rate(manager, user_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    return await service.to_read(user)
