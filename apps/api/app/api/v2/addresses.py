"""API v2 organization address book: клиентская адресная книга доставки.

Этап 2 дорожной карты (`docs/FEATURES_ROADMAP.md`). Чтение — любой член
организации; запись — OWNER/BUYER. У legacy-одиночек (без организации)
адресной книги нет: GET отдаёт пустой список, POST отклоняется.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    problem_responses,
    request_id_for,
)
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.schemas.v2.organizations import (
    OrganizationAddressCreate,
    OrganizationAddressOut,
    OrganizationAddressPatch,
)
from app.services.organizations import (
    OrganizationAddressError,
    OrganizationAddressService,
)

router = APIRouter(prefix="/me/organization/addresses", tags=["organization-addresses"])


def _address_out(address) -> OrganizationAddressOut:
    """Ручная проекция ORM → DTO (from_attributes в V2Model не включён)."""
    return OrganizationAddressOut(
        id=address.id,
        kind=address.kind,
        label=address.label,
        recipient_name=address.recipient_name,
        phone=address.phone,
        address_line=address.address_line,
        city=address.city,
        postal_code=address.postal_code,
        country_code=address.country_code,
        is_default=address.is_default,
        created_at=address.created_at,
        updated_at=address.updated_at,
    )


def _as_v2_problem(exc: OrganizationAddressError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _validated_idempotency_key(value: str | None) -> str:
    """Тот же формат, что у заказов v2: 1..255 символов без управляющих."""
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 255 or any(ord(c) < 33 for c in normalized):
        raise V2ProblemError(
            code="VALIDATION_ERROR",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Ошибка валидации",
            detail="Idempotency-Key должен содержать от 1 до 255 допустимых символов",
        )
    return normalized


@router.get(
    "",
    response_model=SuccessResponse[list[OrganizationAddressOut]],
    response_model_by_alias=True,
    responses=problem_responses({401: "Authentication required"}),
)
async def list_addresses(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[list[OrganizationAddressOut]]:
    addresses = await OrganizationAddressService(db).list_addresses(user)
    return SuccessResponse[list[OrganizationAddressOut]](
        data=[_address_out(a) for a in addresses],
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[OrganizationAddressOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Writer role required",
            409: "No organization for address book",
            422: "Validation error",
        }
    ),
)
async def create_address(
    request: Request,
    payload: OrganizationAddressCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationAddressOut]:
    _validated_idempotency_key(idempotency_key)
    try:
        address = await OrganizationAddressService(db).create_address(
            user,
            kind=payload.kind,
            address_line=payload.address_line,
            label=payload.label,
            recipient_name=payload.recipient_name,
            phone=payload.phone,
            city=payload.city,
            postal_code=payload.postal_code,
            country_code=payload.country_code,
            is_default=payload.is_default,
        )
    except OrganizationAddressError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[OrganizationAddressOut](
        data=_address_out(address),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


def _patch_changes(payload: OrganizationAddressPatch) -> dict[str, object]:
    """Явно переданные поля → changes. null у NOT NULL колонок — 422.

    pydantic model_fields_set различает «поле отсутствует» и «поле = null»:
    absent сохраняет прежнее значение, null у nullable-колонок очищает его.
    """
    changes: dict[str, object] = {}
    clearable = ("label", "recipient_name", "phone", "city", "postal_code")
    required = ("kind", "address_line", "country_code")
    for name in (*clearable, *required, "is_default"):
        if name not in payload.model_fields_set:
            continue
        value = getattr(payload, name)
        if value is None and name in required:
            raise V2ProblemError(
                code="VALIDATION_ERROR",
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Ошибка валидации",
                detail=f"Поле {name} обязательно и не может быть null",
            )
        changes[name] = value
    return changes


@router.patch(
    "/{addressId}",
    response_model=SuccessResponse[OrganizationAddressOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Writer role required",
            404: "Address not found in current organization",
            409: "Duplicate address line",
            422: "Validation error",
        }
    ),
)
async def update_address(
    request: Request,
    payload: OrganizationAddressPatch,
    address_id: uuid.UUID = Path(alias="addressId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationAddressOut]:
    try:
        address = await OrganizationAddressService(db).update_address(
            user,
            address_id=address_id,
            changes=_patch_changes(payload),
        )
    except OrganizationAddressError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[OrganizationAddressOut](
        data=_address_out(address),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.delete(
    "/{addressId}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Writer role required",
            404: "Address not found in current organization",
            # 422 объявляем явно: иначе FastAPI подставит автосхему с
            # application/json и нарушит Problem Details-контракт (снапшот).
            422: "Validation error",
        }
    ),
)
async def delete_address(
    request: Request,
    address_id: uuid.UUID = Path(alias="addressId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await OrganizationAddressService(db).delete_address(user, address_id=address_id)
    except OrganizationAddressError as exc:
        raise _as_v2_problem(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
