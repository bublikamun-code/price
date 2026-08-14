"""Роутер заявок клиента. См. ARCHITECTURE_PLAN.md §6, §9.

Создание заявки замораживает цены/курс (§17.2). Клиент видит только свои заявки.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.user import User
from app.repositories import orders as orders_repo
from app.schemas import MetaPage
from app.schemas.cart import CartRead
from app.schemas.order import (
    OrderCreate,
    OrderItemRead,
    OrderListPage,
    OrderRead,
)
from app.services.order import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


def _from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = (
        status.HTTP_404_NOT_FOUND
        if "не найден" in msg
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=msg)


async def _to_read(
    db: AsyncSession, order: Order, *, with_items: bool
) -> OrderRead:
    items = None
    if with_items:
        rows = await orders_repo.get_order_items(db, order_id=order.id)
        items = [OrderItemRead.model_validate(i) for i in rows]
    return OrderRead.model_validate(order).model_copy(update={"items": items})


@router.get("", response_model=OrderListPage)
async def list_orders(
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderListPage:
    rows, total = await OrderService(db).list_for_client(
        user, status_filter, page, per_page
    )
    data = [await _to_read(db, o, with_items=False) for o in rows]
    return OrderListPage(data=data, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    service = OrderService(db)
    try:
        order = await service.create(user, payload)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    await db.refresh(order)
    return await _to_read(db, order, with_items=True)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    try:
        order = await OrderService(db).get(user, order_id, as_manager=False)
    except ValueError as e:
        raise _from_value_error(e)
    return await _to_read(db, order, with_items=True)


@router.post("/{order_id}/repeat", response_model=CartRead)
async def repeat_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    try:
        cart = await OrderService(db).repeat(user, order_id)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return cart


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    service = OrderService(db)
    try:
        order = await service.cancel(user, order_id)
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
