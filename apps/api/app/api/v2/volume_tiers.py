"""API v2: скидки за объём (§6 «Скидки за объём», §16 п.41).

Четыре эндпоинта канона:
  GET    /manager/brands/{brandId}/volume-tiers   — лестница бренда
  POST   /manager/brands/{brandId}/volume-tiers   — добавить ступень (201)
  PATCH  /manager/volume-tiers/{tierId}          — правка, If-Match по версии ступени
  DELETE /manager/volume-tiers/{tierId}          — удаление, If-Match

``If-Match`` сверяет версию **ступени**, а не бренда (§16 п.41 п.8): правка порога
и правка процента — независимые изменения, и общая версия бренда заставила бы
менеджера перезагружать чужую правку. Роутер тонкий, доменные ошибки мапятся в
RFC 9457 Problem Details.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    parse_if_match,
    problem_responses,
    request_id_for,
)
from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.schemas.v2.volume_tiers import (
    VolumeTierCreateIn,
    VolumeTierOut,
    VolumeTierUpdateIn,
    volume_tier_out,
)
from app.services.volume_tiers import VolumeTierError, VolumeTierService

router = APIRouter(prefix="/manager", tags=["manager:volume-tiers"])

_PROBLEM_RESPONSES = problem_responses(
    {
        400: "Invalid If-Match",
        401: "Authentication required",
        403: "Manager role required",
        404: "Brand or volume tier not found",
        409: "Stale resource version or duplicate threshold",
        422: "Validation error",
        500: "Internal server error",
    }
)


def _as_v2_problem(exc: VolumeTierError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


@router.get(
    "/brands/{brandId}/volume-tiers",
    response_model=SuccessResponse[list[VolumeTierOut]],
    response_model_by_alias=True,
    responses=_PROBLEM_RESPONSES,
)
async def list_volume_tiers(
    request: Request,
    brand_id: uuid.UUID = Path(alias="brandId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[list[VolumeTierOut]]:
    """Лестница бренда по возрастанию порога."""
    service = VolumeTierService(db)
    try:
        tiers = await service.list_for_brand(brand_id=brand_id)
    except VolumeTierError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[list[VolumeTierOut]](
        data=[volume_tier_out(tier) for tier in tiers],
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/brands/{brandId}/volume-tiers",
    response_model=SuccessResponse[VolumeTierOut],
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
    responses=_PROBLEM_RESPONSES,
)
async def create_volume_tier(
    request: Request,
    payload: VolumeTierCreateIn,
    brand_id: uuid.UUID = Path(alias="brandId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[VolumeTierOut]:
    """Добавить ступень. Дубль порога в пределах бренда — 409."""
    service = VolumeTierService(db)
    try:
        tier = await service.create(
            brand_id=brand_id,
            min_qty=payload.min_qty,
            discount_percent=payload.discount_percent,
            actor=manager,
        )
    except VolumeTierError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return SuccessResponse[VolumeTierOut](
        data=volume_tier_out(tier),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.patch(
    "/volume-tiers/{tierId}",
    response_model=SuccessResponse[VolumeTierOut],
    response_model_by_alias=True,
    responses=_PROBLEM_RESPONSES,
)
async def update_volume_tier(
    request: Request,
    payload: VolumeTierUpdateIn,
    tier_id: uuid.UUID = Path(alias="tierId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[VolumeTierOut]:
    """Правка ступени. If-Match — по ``brand_volume_tiers.version`` (§16 п.41 п.8)."""
    expected_version = parse_if_match(if_match)
    service = VolumeTierService(db)
    try:
        tier = await service.update(
            tier_id=tier_id,
            expected_version=expected_version,
            min_qty=payload.min_qty,
            discount_percent=payload.discount_percent,
            actor=manager,
        )
    except VolumeTierError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return SuccessResponse[VolumeTierOut](
        data=volume_tier_out(tier),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.delete(
    "/volume-tiers/{tierId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_PROBLEM_RESPONSES,
)
async def delete_volume_tier(
    tier_id: uuid.UUID = Path(alias="tierId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удалить ступень. If-Match обязателен, stale → 409."""
    expected_version = parse_if_match(if_match)
    service = VolumeTierService(db)
    try:
        await service.delete(
            tier_id=tier_id, expected_version=expected_version, actor=manager
        )
    except VolumeTierError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
