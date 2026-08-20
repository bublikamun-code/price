"""Роутер корзины клиента (persist в БД). См. ARCHITECTURE_PLAN.md §19.

Корзина одна на пользователя; актуальные цены считаются под клиента «на лету».
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.cart import (
    CartBulkAddIn,
    CartBulkAddOut,
    CartItemCreate,
    CartItemUpdate,
    CartRead,
)
from app.services.cart import CartService

router = APIRouter(prefix="/cart", tags=["cart"])


def _from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = (
        status.HTTP_404_NOT_FOUND
        if "не найден" in msg or "нет в" in msg
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=msg)


@router.get("", response_model=CartRead)
async def get_cart(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    cart = await CartService(db).view(user)
    await db.commit()
    return cart


@router.post("/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
async def add_item(
    payload: CartItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    try:
        cart = await CartService(db).add(
            user, payload.sku, payload.quantity, payload.note
        )
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return cart


@router.post("/items/bulk", response_model=CartBulkAddOut)
async def add_items_bulk(
    payload: CartBulkAddIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartBulkAddOut:
    """Массовое добавление позиций (§16 п.20-5) — частичный успех, код 200.

    Валидные позиции аккумулируются с уже лежащими в корзине; отклонённые
    (не найден / архив) возвращаются с причиной. Лимит: 1..500 позиций.
    """
    result = await CartService(db).add_bulk(user, payload.items)
    await db.commit()
    return result


@router.put("/items/{sku}", response_model=CartRead)
async def update_item(
    sku: str,
    payload: CartItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    try:
        cart = await CartService(db).update(
            user, sku, payload.quantity, payload.note
        )
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return cart


@router.delete("/items/{sku}", response_model=CartRead)
async def delete_item(
    sku: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    try:
        cart = await CartService(db).delete_item(user, sku)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return cart


@router.delete("", response_model=CartRead)
async def clear_cart(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CartRead:
    cart = await CartService(db).clear(user)
    await db.commit()
    return cart
