"""Роутер курсов валют менеджера (/api/v1/manager/currencies). См. §6, §17, §16 п.19."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.currency import ManualRateIn, RateOut, RatesOut
from app.services.currency import CurrencyService, refresh_nbrb

router = APIRouter(prefix="/currencies", tags=["manager:currencies"])


@router.get("/rates", response_model=RatesOut)
async def list_rates(
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> RatesOut:
    rates = await CurrencyService(db).list_rates()
    return RatesOut(data=[RateOut.model_validate(r) for r in rates])


@router.post("/rate", response_model=RateOut, status_code=status.HTTP_201_CREATED)
async def set_manual_rate(
    payload: ManualRateIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> RateOut:
    rate = await CurrencyService(db).set_manual_rate(manager, payload)
    return RateOut.model_validate(rate)


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_rates(
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> dict[str, bool]:
    refresh_nbrb()
    return {"queued": True}
