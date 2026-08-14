"""Роутер заявок менеджера. См. ARCHITECTURE_PLAN.md §6, §9.

Менеджер видит все заявки и меняет статусы (FSM, §9) с записью в audit_log.
Все эндпоинты требуют роль MANAGER (§11 RBAC).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.orders import _to_read
from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.user import User
from app.schemas import MetaPage
from app.schemas.order import OrderListPage, OrderRead, OrderStatusUpdate
from app.services.order import OrderService

router = APIRouter(prefix="/orders", tags=["manager:orders"])


@router.get("", response_model=OrderListPage)
async def list_orders(
    client: uuid.UUID | None = Query(default=None, description="Фильтр по клиенту"),
    manager: uuid.UUID | None = Query(default=None, description="Фильтр по менеджеру"),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> OrderListPage:
    rows, total = await OrderService(db).list_for_manager(
        client_id=client, status=status_filter, manager_id=manager,
        page=page, per_page=per_page,
    )
    data = [await _to_read(db, o, with_items=False) for o in rows]
    return OrderListPage(data=data, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: uuid.UUID,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    try:
        order = await OrderService(db).get(manager, order_id, as_manager=True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return await _to_read(db, order, with_items=True)


@router.patch("/{order_id}", response_model=OrderRead)
async def update_order(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    service = OrderService(db)
    try:
        order = await service.change_status(
            manager, order_id, payload.status, payload.manager_id
        )
    except ValueError as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "не найден" in msg
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=msg)
    await db.commit()
    await db.refresh(order)
    return await _to_read(db, order, with_items=True)
