"""Organization-scoped API v2 cart endpoints with optimistic concurrency."""
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
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.v2.cart import CartItemAdd, CartItemReplace, CartSummary
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.services.cart_v2 import CartV2Error, CartV2Service
from app.services.organizations import OrganizationContextService

router = APIRouter(prefix="/cart", tags=["cart"])

_CART_ERRORS = {
    400: "Invalid If-Match or unavailable product",
    401: "Authentication required",
    403: "Client role required",
    404: "Product or cart item not found",
    409: "Stale cart version",
    422: "Validation error or quantity overflow",
    500: "Internal server error",
}


def _require_client(user: User) -> None:
    if user.role != UserRole.CLIENT:
        raise V2ProblemError(
            code="PERMISSION_DENIED",
            status=status.HTTP_403_FORBIDDEN,
            title="Недостаточно прав",
            detail="Корзина доступна только клиентам",
        )


def _problem(exc: CartV2Error) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _success(
    request: Request, response: Response, cart: CartSummary
) -> SuccessResponse[CartSummary]:
    response.headers["ETag"] = f'"{cart.version}"'
    return SuccessResponse[CartSummary](
        data=cart,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {401: "Authentication required", 403: "Client role required", 500: "Internal server error"}
    ),
)
async def get_cart(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    _require_client(user)
    context = await OrganizationContextService(db).resolve(user)
    cart = await CartV2Service(db).view(
        user, organization_id=context.organization_id
    )
    await db.commit()
    return _success(request, response, cart)


@router.post(
    "/items",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(_CART_ERRORS),
)
async def add_cart_item(
    request: Request,
    response: Response,
    payload: CartItemAdd,
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    _require_client(user)
    expected_version = parse_if_match(if_match)
    context = await OrganizationContextService(db).resolve(user)
    try:
        cart = await CartV2Service(db).add(
            user,
            organization_id=context.organization_id,
            expected_version=expected_version,
            product_id=payload.product_id,
            quantity=payload.quantity,
            note=payload.note,
        )
    except CartV2Error as exc:
        raise _problem(exc) from exc
    await db.commit()
    return _success(request, response, cart)


@router.put(
    "/items/{productId}",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(_CART_ERRORS),
)
async def replace_cart_item(
    request: Request,
    response: Response,
    payload: CartItemReplace,
    product_id: uuid.UUID = Path(alias="productId"),
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    _require_client(user)
    expected_version = parse_if_match(if_match)
    context = await OrganizationContextService(db).resolve(user)
    try:
        cart = await CartV2Service(db).replace_item(
            user,
            organization_id=context.organization_id,
            expected_version=expected_version,
            product_id=product_id,
            quantity=payload.quantity,
            note=payload.note,
        )
    except CartV2Error as exc:
        raise _problem(exc) from exc
    await db.commit()
    return _success(request, response, cart)


@router.delete(
    "/items/{productId}",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(_CART_ERRORS),
)
async def delete_cart_item(
    request: Request,
    response: Response,
    product_id: uuid.UUID = Path(alias="productId"),
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    _require_client(user)
    expected_version = parse_if_match(if_match)
    context = await OrganizationContextService(db).resolve(user)
    try:
        cart = await CartV2Service(db).delete_item(
            user,
            organization_id=context.organization_id,
            expected_version=expected_version,
            product_id=product_id,
        )
    except CartV2Error as exc:
        raise _problem(exc) from exc
    await db.commit()
    return _success(request, response, cart)


@router.delete(
    "",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(_CART_ERRORS),
)
async def clear_cart(
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    _require_client(user)
    expected_version = parse_if_match(if_match)
    context = await OrganizationContextService(db).resolve(user)
    try:
        cart = await CartV2Service(db).clear(
            user,
            organization_id=context.organization_id,
            expected_version=expected_version,
        )
    except CartV2Error as exc:
        raise _problem(exc) from exc
    await db.commit()
    return _success(request, response, cart)
