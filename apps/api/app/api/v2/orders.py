"""Read-only API v2 order collection and detail."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    parse_if_match,
    problem_responses,
    request_id_for,
)
from app.api.v2.pagination import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    filter_signature,
)
from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order
from app.models.user import User
from app.repositories import orders as orders_repo
from app.schemas.v2.cart import CartSummary
from app.schemas.v2.common import (
    CursorMeta,
    CursorResponse,
    ProblemFieldError,
    ResponseMeta,
    SuccessResponse,
)
from app.schemas.v2.orders import (
    OrderCreate,
    OrderDetail,
    OrderSummary,
    order_detail,
    order_summary,
)
from app.services import email as email_service
from app.services.cart_v2 import CartV2Error
from app.services.order import OrderError, OrderService
from app.services.organizations import OrganizationContextService

router = APIRouter(prefix="/orders", tags=["orders"])

_ORDER_SORT = "createdAt,id"
_ORDER_CURSOR_RESOURCE = "orders"


def _order_filter_signature(
    user: User,
    context,
    status: OrderStatus | None,
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    min_total: Decimal | None,
    max_total: Decimal | None,
) -> str:
    """Bind the cursor to the full filter set (Этап 1: поиск, даты, сумма)."""
    return filter_signature(
        str(user.id),
        str(context.organization_id) if context.organization_id else None,
        status.value if status is not None else None,
        q,
        date_from.isoformat() if date_from is not None else None,
        date_to.isoformat() if date_to is not None else None,
        str(min_total) if min_total is not None else None,
        str(max_total) if max_total is not None else None,
    )


def _decode_order_cursor(
    cursor: str | None,
    *,
    user: User,
    context,
    status: OrderStatus | None,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    min_total: Decimal | None,
    max_total: Decimal | None,
) -> dict[str, str] | None:
    if cursor is None:
        return None
    try:
        decoded = decode_cursor(
            cursor,
            resource=_ORDER_CURSOR_RESOURCE,
            sort=_ORDER_SORT,
            filter_sig=_order_filter_signature(
                user,
                context,
                status,
                q=q,
                date_from=date_from,
                date_to=date_to,
                min_total=min_total,
                max_total=max_total,
            ),
        )
        # Authenticate the complete payload first, then validate its key value.
        datetime.fromisoformat(decoded["value"])
        return decoded
    except (InvalidCursorError, ValueError, TypeError) as exc:
        raise V2ProblemError(
            code="VALIDATION_ERROR",
            status=422,
            title="Ошибка валидации",
            detail="Курсор пагинации недействителен",
        ) from exc


def _as_v2_problem(exc: OrderError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _validated_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255 or any(ord(char) < 33 for char in normalized):
        raise V2ProblemError(
            code="VALIDATION_ERROR",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Ошибка валидации",
            detail="Idempotency-Key должен содержать от 1 до 255 допустимых символов",
            errors=[
                ProblemFieldError(
                    field="Idempotency-Key",
                    code="INVALID_IDEMPOTENCY_KEY",
                    message="Некорректный Idempotency-Key",
                )
            ],
        )
    return normalized


def _notify_manager_order_created(
    order: Order, client: User, *, items_count: int
) -> None:
    """Keep the fire-and-forget manager notification compatible with v1."""
    if not settings.manager_notify_email:
        return
    subject, html_body = email_service.build_order_created_manager_email(
        order_no=email_service.format_order_no(order.seq),
        client_name=client.full_name,
        client_company=client.company,
        total_amount=float(order.total_amount),
        currency_code=order.currency_code,
        delivery_method=order.delivery_method,
        items_count=items_count,
    )
    email_service.queue_email(
        to=settings.manager_notify_email, subject=subject, html_body=html_body
    )


@router.get(
    "",
    response_model=CursorResponse[OrderSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_orders(
    request: Request,
    status: OrderStatus | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    min_total: Decimal | None = Query(default=None, ge=0),
    max_total: Decimal | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[OrderSummary]:
    context = await OrganizationContextService(db).resolve(user)
    after = _decode_order_cursor(
        cursor,
        user=user,
        context=context,
        status=status,
        q=q,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        max_total=max_total,
    )
    rows = await OrderService(db).list_for_client_v2(
        user,
        context=context,
        status=status,
        limit=limit + 1,
        after=after,
        q=q,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        max_total=max_total,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    filter_sig = _order_filter_signature(
        user,
        context,
        status,
        q=q,
        date_from=date_from,
        date_to=date_to,
        min_total=min_total,
        max_total=max_total,
    )
    next_cursor = (
        encode_cursor(
            resource=_ORDER_CURSOR_RESOURCE,
            sort=_ORDER_SORT,
            filter_sig=filter_sig,
            value=rows[-1].created_at.isoformat(),
            item_id=rows[-1].id,
        )
        if has_more and rows
        else None
    )
    return CursorResponse[OrderSummary](
        data=[order_summary(order) for order in rows],
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=_ORDER_SORT,
        ),
    )


@router.post(
    "",
    response_model=SuccessResponse[OrderDetail],
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(
        {
            400: "Product unavailable",
            401: "Authentication required",
            403: "Client role required",
            404: "Product not found",
            409: "Idempotency conflict or insufficient stock",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def create_order(
    request: Request,
    response: Response,
    payload: OrderCreate,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrderDetail]:
    if user.role != UserRole.CLIENT:
        raise V2ProblemError(
            code="PERMISSION_DENIED",
            status=status.HTTP_403_FORBIDDEN,
            title="Недостаточно прав",
            detail="Создание заявки доступно только клиентам",
        )

    key = _validated_idempotency_key(idempotency_key)
    service = OrderService(db)
    context = await OrganizationContextService(db).resolve(user)
    request_hash = await service.request_fingerprint_v2(
        user, payload, context=context
    )

    try:
        replayed = await service.find_idempotent_order(
            user,
            idempotency_key=key,
            request_hash=request_hash,
        )
        if replayed is not None:
            items = await orders_repo.get_order_items(db, order_id=replayed.id)
            response.headers["X-Idempotency-Replayed"] = "true"
            return SuccessResponse[OrderDetail](
                data=order_detail(replayed, items),
                meta=ResponseMeta(request_id=request_id_for(request)),
            )

        record = await service.reserve_idempotency(
            user,
            idempotency_key=key,
            request_hash=request_hash,
        )
        if record is None:
            replayed = await service.find_idempotent_order(
                user,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if replayed is None:
                raise V2ProblemError(
                    code="CONFLICT",
                    status=status.HTTP_409_CONFLICT,
                    title="Конфликт состояния",
                    detail="Не удалось повторно получить результат создания заявки",
                )
            items = await orders_repo.get_order_items(db, order_id=replayed.id)
            response.headers["X-Idempotency-Replayed"] = "true"
            return SuccessResponse[OrderDetail](
                data=order_detail(replayed, items),
                meta=ResponseMeta(request_id=request_id_for(request)),
            )

        order = await service.create_v2(user, payload, context=context)
        record.order_id = order.id
        await db.flush()
        items = await orders_repo.get_order_items(db, order_id=order.id)
        detail = order_detail(order, items)
    except OrderError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    response.headers["X-Idempotency-Replayed"] = "false"
    _notify_manager_order_created(order, user, items_count=len(payload.items))
    return SuccessResponse[OrderDetail](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/{orderId}",
    response_model=SuccessResponse[OrderDetail],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Order not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_order(
    request: Request,
    order_id: uuid.UUID = Path(alias="orderId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrderDetail]:
    try:
        order = await OrderService(db).get(user, order_id, as_manager=False)
        items = await orders_repo.get_order_items(db, order_id=order.id)
    except OrderError as exc:
        raise _as_v2_problem(exc) from exc

    return SuccessResponse[OrderDetail](
        data=order_detail(order, items),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/{orderId}/cancel",
    response_model=SuccessResponse[OrderDetail],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Order not found",
            409: "Order cannot be cancelled",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def cancel_order(
    request: Request,
    order_id: uuid.UUID = Path(alias="orderId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrderDetail]:
    try:
        order = await OrderService(db).cancel(user, order_id)
    except OrderError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    await db.refresh(order)
    items = await orders_repo.get_order_items(db, order_id=order.id)
    return SuccessResponse[OrderDetail](
        data=order_detail(order, items),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/{orderId}/repeat",
    response_model=SuccessResponse[CartSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid If-Match",
            401: "Authentication required",
            403: "Client role required",
            404: "Order not found",
            409: "Cart scope or version conflict",
            422: "Validation error or quantity overflow",
            500: "Internal server error",
        }
    ),
)
async def repeat_order(
    request: Request,
    response: Response,
    order_id: uuid.UUID = Path(alias="orderId"),
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CartSummary]:
    if user.role != UserRole.CLIENT:
        raise V2ProblemError(
            code="PERMISSION_DENIED",
            status=status.HTTP_403_FORBIDDEN,
            title="Недостаточно прав",
            detail="Повтор заявки доступен только клиентам",
        )
    expected_version = parse_if_match(if_match)
    context = await OrganizationContextService(db).resolve(user)
    try:
        cart = await OrderService(db).repeat_v2(
            user,
            order_id,
            organization_id=context.organization_id,
            expected_version=expected_version,
        )
    except OrderError as exc:
        raise _as_v2_problem(exc) from exc
    except CartV2Error as exc:
        raise V2ProblemError(
            code=exc.code,
            status=exc.status_code,
            title=exc.title,
            detail=exc.detail,
        ) from exc
    await db.commit()
    response.headers["ETag"] = f'"{cart.version}"'
    return SuccessResponse[CartSummary](
        data=cart,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )
