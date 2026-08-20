"""Роутер товаров менеджера (/api/v1/manager/products). См. §6, §16 п.20-2.

Список с фильтрами (в отличие от клиентского каталога виден и ARCHIVED) и
точечный PATCH ручной цены/статуса; мутации пишут audit_log и инвалидируют
кэш каталога. Все эндпоинты требуют роль MANAGER (§11 RBAC).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import StockStatus, UserRole
from app.models.user import User
from app.schemas import MetaPage
from app.schemas.manager_catalog import (
    ManagerProductPage,
    ManagerProductPatchIn,
    ManagerProductRead,
)
from app.services.manager_catalog import (
    ConflictError,
    ManagerCatalogService,
    NotFoundError,
)

router = APIRouter(prefix="/products", tags=["manager:products"])


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, ConflictError → 409, прочие ValueError → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("", response_model=ManagerProductPage)
async def list_products(
    q: str | None = Query(default=None, description="Поиск: артикул/наименование"),
    brand_id: uuid.UUID | None = Query(default=None),
    stock: StockStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagerProductPage:
    items, total = await ManagerCatalogService(db).list_products(
        q=q, brand_id=brand_id, stock=stock, page=page, per_page=per_page
    )
    return ManagerProductPage(data=items, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.patch("/{product_id}", response_model=ManagerProductRead)
async def update_product(
    product_id: uuid.UUID,
    payload: ManagerProductPatchIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagerProductRead:
    """Ручная цена (``override_price``, null — сброс) и/или статус остатка."""
    try:
        return await ManagerCatalogService(db).update_product(manager, product_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
