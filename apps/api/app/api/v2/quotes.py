"""API v2: коммерческие предложения (этап 8 роадмапа).

docs/FEATURES_ROADMAP.md «Этап 8. Коммерческие предложения».

Эндпоинты канона:
  manager:
    GET    /manager/quotes                  — коллекция (курсор, фильтр status)
    POST   /manager/quotes                  — создать DRAFT (201)
    GET    /manager/quotes/{quoteId}        — деталь
    PATCH  /manager/quotes/{quoteId}        — правка DRAFT, If-Match
    DELETE /manager/quotes/{quoteId}        — удалить DRAFT (204)
    POST   /manager/quotes/{quoteId}/send   — DRAFT → SENT (If-Match, лимит)
    POST   /manager/quotes/{quoteId}/pdf    — СИНХРОННЫЙ рендер PDF (без Celery)
  клиент:
    GET    /quotes                          — КП своей активной организации
    GET    /quotes/{quoteId}                — деталь (DRAFT → 404)
    POST   /quotes/{quoteId}/accept         — принять → заявка (Idempotency-Key)
    POST   /quotes/{quoteId}/reject         — отклонить
    GET    /quotes/{quoteId}/pdf/download   — PDF байтами (не presigned)

Роутер тонкий: правила и жизненный цикл — в ``services/quote.py``, доменные
ошибки мапятся в RFC 9457 Problem Details. Клиент видит КП только своей
активной организации (org-scope; чужое и DRAFT → 404 без утечки). Публичных
токен-ссылок нет (этап 8: «КП видно клиенту в кабинете org-scope»).
Скачивание байтами, а не presigned — урок mixed-content 27.09 (§16 п.37).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
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
from app.core.deps import get_current_user, require_role
from app.core.limiter import limiter
from app.core.sanitize import content_disposition
from app.db.session import get_db
from app.models.enums import FileAssetType, QuotePdfStatus, QuoteStatus, UserRole
from app.models.file import FileAsset
from app.models.user import User
from app.repositories import orders as orders_repo
from app.schemas.v2.common import (
    CursorMeta,
    CursorResponse,
    ProblemFieldError,
    ResponseMeta,
    SuccessResponse,
)
from app.schemas.v2.orders import OrderDetail, order_detail
from app.schemas.v2.quotes import (
    QuoteAcceptCreate,
    QuoteCreate,
    QuoteEdit,
    QuoteOut,
    QuoteStatusOut,
    QuoteSummary,
    quote_out,
    quote_summary,
)
from app.services import storage
from app.services.order import OrderError
from app.services.organizations import OrganizationContextService
from app.services.quote import QuoteError, QuoteService, quote_accept_fingerprint

router = APIRouter(prefix="/quotes", tags=["quotes"])
manager_router = APIRouter(prefix="/manager", tags=["manager:quotes"])

_QUOTE_SORT = "createdAt,id"
_QUOTE_CURSOR_RESOURCE = "quotes"


def _as_v2_problem(exc) -> V2ProblemError:
    """Доменная ошибка (QuoteError/OrderError) → Problem Details.

    Утиной типизацией: accept может упасть и ошибкой заявки
    (``QuoteProductUnavailableError``/``StockExceededError``) — машинные коды
    у обеих иерархий одинаково стабильны.
    """
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _validated_idempotency_key(value: str) -> str:
    """Формат Idempotency-Key — тот же, что у заказов/счётов v2 (§11)."""
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 255
        or any(ord(char) < 33 for char in normalized)
    ):
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


def _quote_filter_signature(scope: str, quote_status: QuoteStatus | None) -> str:
    """Курсор привязан к scope (org / manager) и статусному фильтру."""
    return filter_signature(
        scope,
        quote_status.value if quote_status is not None else None,
    )


def _decode_quote_cursor(
    cursor: str | None,
    *,
    scope: str,
    quote_status: QuoteStatus | None,
) -> dict[str, str] | None:
    if cursor is None:
        return None
    try:
        decoded = decode_cursor(
            cursor,
            resource=_QUOTE_CURSOR_RESOURCE,
            sort=_QUOTE_SORT,
            filter_sig=_quote_filter_signature(scope, quote_status),
        )
        datetime.fromisoformat(decoded["value"])
        return decoded
    except (InvalidCursorError, ValueError, TypeError) as exc:
        raise V2ProblemError(
            code="VALIDATION_ERROR",
            status=422,
            title="Ошибка валидации",
            detail="Курсор пагинации недействителен",
        ) from exc


def _content_disposition(filename: str) -> str:
    """attachment с UTF-8 именем (общая санитизация с документами, §11)."""
    return content_disposition(filename, default="quote.pdf")


# ------------------------------------------------------------------ manager
@manager_router.get(
    "/quotes",
    response_model=CursorResponse[QuoteSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_quotes_manager(
    request: Request,
    quote_status: QuoteStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[QuoteSummary]:
    """Коллекция КП по всем организациям (курсор, фильтр по статусу)."""
    scope = "manager"
    after = _decode_quote_cursor(cursor, scope=scope, quote_status=quote_status)
    rows = await QuoteService(db).list_for_manager(
        status=quote_status,
        limit=limit + 1,
        after=after,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(
            resource=_QUOTE_CURSOR_RESOURCE,
            sort=_QUOTE_SORT,
            filter_sig=_quote_filter_signature(scope, quote_status),
            value=rows[-1].created_at.isoformat(),
            item_id=rows[-1].id,
        )
        if has_more and rows
        else None
    )
    # Ленивое истечение срока могло пометить строки EXPIRED — коммитим.
    await db.commit()
    return CursorResponse[QuoteSummary](
        data=[quote_summary(quote) for quote in rows],
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=_QUOTE_SORT,
        ),
    )


@manager_router.post(
    "/quotes",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization not found",
            409: "Quote item or product unavailable",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def create_quote(
    request: Request,
    payload: QuoteCreate,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """Создать DRAFT КП: позиции — снапшот каталога с override-ценой."""
    service = QuoteService(db)
    try:
        quote = await service.create(manager, payload)
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.get(
    "/quotes/{quoteId}",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Quote not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_quote_manager(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """Деталь КП (менеджер — без org-ограничений)."""
    service = QuoteService(db)
    try:
        quote = await service.get_for_manager(quote_id)
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.patch(
    "/quotes/{quoteId}",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid If-Match or validUntil in the past",
            401: "Authentication required",
            403: "Manager role required",
            404: "Quote not found",
            409: "Not a draft, stale version or unavailable item",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def edit_quote(
    request: Request,
    payload: QuoteEdit,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """Правка DRAFT (If-Match): замена позиций и/или validUntil; version+1."""
    expected_version = parse_if_match(if_match)
    service = QuoteService(db)
    try:
        quote = await service.edit(
            manager, quote_id, payload, expected_version=expected_version
        )
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.delete(
    "/quotes/{quoteId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Quote not found",
            409: "Not a draft",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def delete_quote(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удалить DRAFT КП (204). Позиции удаляются каскадом; аудит — quote.delete."""
    service = QuoteService(db)
    try:
        await service.delete(manager, quote_id)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@manager_router.post(
    "/quotes/{quoteId}/send",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid If-Match, missing or past validUntil",
            401: "Authentication required",
            403: "Manager role required",
            404: "Quote not found",
            409: "Not a draft or stale version",
            422: "Validation error",
            429: "Too many quotes sent",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_invoice_issue)
async def send_quote(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """DRAFT → SENT: номер ``КП-YYYY-NNNNNN``, заморозка total, NEW_QUOTE
    участникам организации. Требует If-Match по версии КП."""
    expected_version = parse_if_match(if_match)
    service = QuoteService(db)
    try:
        quote = await service.send(
            manager, quote_id, expected_version=expected_version
        )
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    # SSE-события NEW_QUOTE — ПОСЛЕ коммита (fail-open; §16 п.26).
    service.publish_quote_notifications()
    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.post(
    "/quotes/{quoteId}/pdf",
    response_model=SuccessResponse[QuoteStatusOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Quote not found",
            409: "Quote is not sent yet",
            422: "Validation error",
            502: "Storage unavailable",
            500: "Internal server error",
        }
    ),
)
async def render_quote_pdf(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteStatusOut]:
    """Синхронный рендер PDF КП (этап 8, без Celery): HTML → weasyprint → S3 →
    FileAsset(QUOTE_PDF). Повторный вызов перерендеривает (заменяет asset)."""
    service = QuoteService(db)
    try:
        quote = await service.get_for_manager(quote_id)
        quote = await service.render_pdf(quote)
        data = QuoteStatusOut(
            id=quote.id,
            pdf_status=quote.pdf_status,
            pdf_file_asset_id=quote.pdf_file_asset_id,
        )
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc
    except storage.StorageError as exc:
        # PDF-флаг FAILED уже записан сервисом — коммитим его до problem-ответа,
        # чтобы UI показал кнопку повторного рендера.
        await db.commit()
        raise V2ProblemError(
            code="STORAGE_UNAVAILABLE",
            status=status.HTTP_502_BAD_GATEWAY,
            title="Хранилище недоступно",
            detail="Не удалось сохранить PDF коммерческого предложения",
        ) from exc

    await db.commit()
    return SuccessResponse[QuoteStatusOut](
        data=data,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


# ------------------------------------------------------------------- client
@router.get(
    "",
    response_model=CursorResponse[QuoteSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_quotes_client(
    request: Request,
    quote_status: QuoteStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[QuoteSummary]:
    """КП активной организации клиента (org-scope); DRAFT не видны."""
    context = await OrganizationContextService(db).resolve(user)
    scope = (
        str(context.organization_id) if context.organization_id else "none"
    )
    after = _decode_quote_cursor(cursor, scope=scope, quote_status=quote_status)
    rows = await QuoteService(db).list_for_client(
        user,
        status=quote_status,
        limit=limit + 1,
        after=after,
        context=context,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(
            resource=_QUOTE_CURSOR_RESOURCE,
            sort=_QUOTE_SORT,
            filter_sig=_quote_filter_signature(scope, quote_status),
            value=rows[-1].created_at.isoformat(),
            item_id=rows[-1].id,
        )
        if has_more and rows
        else None
    )
    # Ленивое истечение срока могло пометить строки EXPIRED — коммитим.
    await db.commit()
    return CursorResponse[QuoteSummary](
        data=[quote_summary(quote) for quote in rows],
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=_QUOTE_SORT,
        ),
    )


@router.get(
    "/{quoteId}",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Quote not found or still a draft",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_quote_client(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """Деталь КП своей организации; чужое и DRAFT → 404 (без утечки)."""
    service = QuoteService(db)
    try:
        quote = await service.get_for_client(user, quote_id)
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    # Ленивое истечение срока могло пометить строку EXPIRED — коммитим.
    await db.commit()
    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/{quoteId}/accept",
    response_model=SuccessResponse[OrderDetail],
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Client role required",
            404: "Quote not found",
            409: "Quote not sent/expired/decided, product unavailable or "
            "insufficient stock",
            422: "Validation error",
            429: "Too many quotes accepted",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_invoice_issue)
async def accept_quote(
    request: Request,
    response: Response,
    payload: QuoteAcceptCreate,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrderDetail]:
    """Принять КП → заявка с ЦЕНАМИ ИЗ КП (этап 8).

    Idempotency-Key обязателен: повтор с тем же ключом возвращает ту же
    заявку (``X-Idempotency-Replayed: true``); accept неSENT/истёкшего/уже
    решённого КП → 409. Корзина не затрагивается; delivery передаётся в теле.
    """
    if user.role != UserRole.CLIENT:
        raise V2ProblemError(
            code="PERMISSION_DENIED",
            status=status.HTTP_403_FORBIDDEN,
            title="Недостаточно прав",
            detail="Принятие КП доступно только клиентам",
        )

    key = _validated_idempotency_key(idempotency_key)
    service = QuoteService(db)
    request_hash = quote_accept_fingerprint(
        user_id=user.id, quote_id=quote_id, delivery=payload.delivery
    )

    try:
        replayed = await service.find_idempotent_order(
            user, idempotency_key=key, request_hash=request_hash
        )
        if replayed is not None:
            items = await orders_repo.get_order_items(db, order_id=replayed.id)
            response.headers["X-Idempotency-Replayed"] = "true"
            return SuccessResponse[OrderDetail](
                data=order_detail(replayed, items),
                meta=ResponseMeta(request_id=request_id_for(request)),
            )

        record = await service.reserve_idempotency(
            user, idempotency_key=key, request_hash=request_hash
        )
        if record is None:
            replayed = await service.find_idempotent_order(
                user, idempotency_key=key, request_hash=request_hash
            )
            if replayed is None:
                raise V2ProblemError(
                    code="CONFLICT",
                    status=status.HTTP_409_CONFLICT,
                    title="Конфликт состояния",
                    detail="Не удалось повторно получить результат принятия КП",
                )
            items = await orders_repo.get_order_items(db, order_id=replayed.id)
            response.headers["X-Idempotency-Replayed"] = "true"
            return SuccessResponse[OrderDetail](
                data=order_detail(replayed, items),
                meta=ResponseMeta(request_id=request_id_for(request)),
            )

        order = await service.accept(user, quote_id, delivery=payload.delivery)
        record.order_id = order.id
        await db.flush()
        items = await orders_repo.get_order_items(db, order_id=order.id)
        detail = order_detail(order, items)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc
    except OrderError as exc:
        # create_from_quote: PRODUCT_NOT_FOUND / PRODUCT_UNAVAILABLE (409) /
        # INSUFFICIENT_STOCK — стабильные коды заказов v2.
        raise _as_v2_problem(exc) from exc

    await db.commit()
    response.headers["X-Idempotency-Replayed"] = "false"
    # In-app QUOTE_ACCEPTED менеджеру-создателю — ПОСЛЕ коммита (fail-open).
    service.publish_status_notification()
    # Запросы визы OWNER'ам — если create_from_quote проставил PENDING (§16 п.42).
    service.orders.publish_approval_requests()
    return SuccessResponse[OrderDetail](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/{quoteId}/reject",
    response_model=SuccessResponse[QuoteOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Client role required",
            404: "Quote not found",
            409: "Quote not sent, expired or already decided",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def reject_quote(
    request: Request,
    quote_id: uuid.UUID = Path(alias="quoteId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[QuoteOut]:
    """Отклонить КП (SENT → REJECTED); повторный reject → 409."""
    if user.role != UserRole.CLIENT:
        raise V2ProblemError(
            code="PERMISSION_DENIED",
            status=status.HTTP_403_FORBIDDEN,
            title="Недостаточно прав",
            detail="Отклонение КП доступно только клиентам",
        )

    service = QuoteService(db)
    try:
        quote = await service.reject(user, quote_id)
        detail = quote_out(quote)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    service.publish_status_notification()
    return SuccessResponse[QuoteOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/{quoteId}/pdf/download",
    response_class=Response,
    responses=problem_responses(
        {
            200: "Quote PDF bytes (application/pdf)",
            401: "Authentication required",
            404: "Quote not found",
            409: "Quote PDF is not ready",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def download_quote_pdf(
    quote_id: uuid.UUID = Path(alias="quoteId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF КП байтами (никогда presigned, §16 п.37): org-scope, DRAFT → 404;
    ``pdf_status != READY`` → 409; хранилище недоступно → 502."""
    service = QuoteService(db)
    try:
        quote = await service.get_for_client(user, quote_id)
    except QuoteError as exc:
        raise _as_v2_problem(exc) from exc

    if quote.pdf_status != QuotePdfStatus.READY or quote.pdf_file_asset_id is None:
        raise V2ProblemError(
            code="QUOTE_PDF_NOT_READY",
            status=status.HTTP_409_CONFLICT,
            title="PDF КП не готов",
            detail=(
                f"PDF КП {quote.number or quote_id} ещё не отрендерен — "
                "запросите его у менеджера"
            ),
        )

    asset = await db.get(FileAsset, quote.pdf_file_asset_id)
    if asset is None or asset.type != FileAssetType.QUOTE_PDF:
        raise V2ProblemError(
            code="QUOTE_NOT_FOUND",
            status=status.HTTP_404_NOT_FOUND,
            title="Коммерческое предложение не найдено",
            detail="Файл КП не найден в архиве",
        )

    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_pdfs, asset.s3_key
        )
    except storage.ObjectNotFound as exc:
        raise V2ProblemError(
            code="QUOTE_NOT_FOUND",
            status=status.HTTP_404_NOT_FOUND,
            title="Коммерческое предложение не найдено",
            detail="Файл КП отсутствует в хранилище",
        ) from exc
    except storage.StorageError as exc:
        raise V2ProblemError(
            code="STORAGE_UNAVAILABLE",
            status=status.HTTP_502_BAD_GATEWAY,
            title="Хранилище недоступно",
            detail="Не удалось прочитать PDF коммерческого предложения",
        ) from exc

    return Response(
        content=data,
        media_type=asset.content_type or "application/pdf",
        headers={
            "Content-Disposition": _content_disposition(asset.filename_display),
            "Cache-Control": "private, max-age=3600",
        },
    )


__all__ = ["manager_router", "router"]
