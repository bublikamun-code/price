"""Роутер избранного клиента. См. ARCHITECTURE_PLAN.md §16.1 (фича A).

Избранное — список отслеживания SKU; источник для PRICE_CHANGED_DIGEST (6.5).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.favorite import FavoriteCreate, FavoriteListPage
from app.services.favorite import FavoriteService

router = APIRouter(prefix="/favorites", tags=["favorites"])


def _from_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = (
        status.HTTP_404_NOT_FOUND
        if "не найден" in msg or "нет в" in msg
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=msg)


@router.get("", response_model=FavoriteListPage)
async def list_favorites(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteListPage:
    return await FavoriteService(db).list(user, page, per_page)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    payload: FavoriteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await FavoriteService(db).add(user, payload.sku)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return {"ok": True}


@router.delete("/{sku}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_favorite(
    sku: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await FavoriteService(db).delete(user, sku)
    except ValueError as e:
        raise _from_value_error(e)
    await db.commit()
    return None
