"""API v2: счёт на оплату (§6 «Счета на оплату», §16 п.40).

Шесть эндпоинтов канона:
  POST   /manager/orders/{orderId}/invoice          — выставить счёт (201)
  POST   /manager/invoices/{invoiceId}/pdf          — перерендерить PDF (202)
  PATCH  /manager/invoices/{invoiceId}              — смена статуса, If-Match
  GET    /orders/{orderId}/invoice                  — счёт по заказу
  GET    /orders/invoices/{invoiceId}/download      — PDF байтами (не presigned)
  (PATCH /manager/organizations/{id} — в api/v2/organizations.py, manager_router)

Роутер тонкий: правила и заморозка — в ``services/invoice.py``, доменные ошибки
мапятся в RFC 9457 Problem Details. Скачивание байтами, а не presigned —
урок mixed-content 27.09 (§16 п.37): внешний S3-хост обслуживается по http и
режется браузером.
"""
from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    parse_if_match,
    problem_responses,
    request_id_for,
)
from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.enums import FileAssetType, InvoicePdfStatus, UserRole
from app.models.file import FileAsset
from app.models.user import User
from app.schemas.v2.common import (
    ProblemFieldError,
    ResponseMeta,
    SuccessResponse,
)
from app.schemas.v2.invoices import InvoiceOut, InvoiceStatusPatch, invoice_out
from app.services import storage
from app.services.invoice import (
    InvoiceError,
    InvoicePdfNotReadyError,
    InvoiceService,
    enqueue_invoice_pdf,
)

router = APIRouter(prefix="/orders", tags=["invoices"])
manager_router = APIRouter(prefix="/manager", tags=["manager:invoices"])


def _as_v2_problem(exc: InvoiceError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _validated_idempotency_key(value: str) -> str:
    """Формат Idempotency-Key — тот же, что у заказов v2 (§11)."""
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


def _content_disposition(filename: str) -> str:
    """attachment с UTF-8 именем: ASCII-фолбэк + RFC 5987 filename*."""
    ascii_fallback = (
        filename.encode("ascii", "ignore").decode("ascii").strip() or "invoice.pdf"
    )
    return (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )


async def _render(
    service: InvoiceService, invoice, *, request: Request
) -> SuccessResponse[InvoiceOut]:
    """Обёртка ответа счёта + реквизиты покупателя из organizations."""
    organization = await service.organization_for_invoice(invoice)
    return SuccessResponse[InvoiceOut](
        data=invoice_out(invoice, organization=organization),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


# ------------------------------------------------------------------ manager
@manager_router.post(
    "/orders/{orderId}/invoice",
    response_model=SuccessResponse[InvoiceOut],
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Order not found",
            409: "Order not invoicable or invoice already exists",
            422: "Validation error",
            429: "Too many invoices issued",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_invoice_issue)
async def issue_invoice(
    request: Request,
    response: Response,
    order_id: uuid.UUID = Path(alias="orderId"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[InvoiceOut]:
    """Выставить счёт по заказу. 1:1 — повтор выдаёт тот же счёт или 409.

    Повтор с тем же ``Idempotency-Key`` возвращает тот же счёт
    (``X-Idempotency-Replayed: true``); новый ключ на тот же заказ — 409
    ``INVOICE_ALREADY_EXISTS`` (§16 п.40 п.1).
    """
    key = _validated_idempotency_key(idempotency_key)
    service = InvoiceService(db)
    request_hash = await service.request_fingerprint(manager, order_id=order_id)
    try:
        replayed = await service.find_idempotent_invoice(
            manager, idempotency_key=key, request_hash=request_hash
        )
        if replayed is not None:
            response.headers["X-Idempotency-Replayed"] = "true"
            return await _render(service, replayed, request=request)

        record = await service.reserve_idempotency(
            manager, idempotency_key=key, request_hash=request_hash
        )
        if record is None:
            replayed = await service.find_idempotent_invoice(
                manager, idempotency_key=key, request_hash=request_hash
            )
            if replayed is None:
                raise InvoiceError(
                    "Не удалось повторно получить результат выставления счёта"
                )
            response.headers["X-Idempotency-Replayed"] = "true"
            return await _render(service, replayed, request=request)

        invoice = await service.issue(manager, order_id)
        record.order_id = invoice.order_id
        await db.flush()
        organization = await service.organization_for_invoice(invoice)
        detail = invoice_out(invoice, organization=organization)
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    response.headers["X-Idempotency-Replayed"] = "false"
    # Задача рендера — ПОСЛЕ коммита: воркер обязан видеть закоммиченный счёт,
    # иначе он прочитает строку, которой ещё (или уже никогда) не будет.
    # Fail-open: счёт выдан, pdf_status=PENDING, неудача постановки в лог.
    enqueue_invoice_pdf(invoice.id)
    return SuccessResponse[InvoiceOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.post(
    "/invoices/{invoiceId}/pdf",
    response_model=SuccessResponse[InvoiceOut],
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Invoice not found",
            409: "Invoice PDF already in progress",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def regenerate_invoice_pdf(
    request: Request,
    invoice_id: uuid.UUID = Path(alias="invoiceId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[InvoiceOut]:
    """Перерендерить PDF после FAILED или после правки реквизитов (§6)."""
    service = InvoiceService(db)
    try:
        invoice = await service.regenerate_pdf(manager, invoice_id)
        organization = await service.organization_for_invoice(invoice)
        detail = invoice_out(invoice, organization=organization)
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    enqueue_invoice_pdf(invoice.id)
    return SuccessResponse[InvoiceOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.patch(
    "/invoices/{invoiceId}",
    response_model=SuccessResponse[InvoiceOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid If-Match",
            401: "Authentication required",
            403: "Manager role required",
            404: "Invoice not found",
            409: "Stale resource version",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def change_invoice_status(
    request: Request,
    payload: InvoiceStatusPatch,
    invoice_id: uuid.UUID = Path(alias="invoiceId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[InvoiceOut]:
    """Смена статуса счёта. If-Match — по версии СЧЁТА, не заказа (§16 п.40 п.8)."""
    expected_version = parse_if_match(if_match)
    service = InvoiceService(db)
    try:
        invoice = await service.change_status(
            manager,
            invoice_id,
            new_status=payload.status,
            expected_version=expected_version,
        )
        organization = await service.organization_for_invoice(invoice)
        detail = invoice_out(invoice, organization=organization)
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc

    await db.commit()
    return SuccessResponse[InvoiceOut](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


# ------------------------------------------------------------------- client
@router.get(
    "/{orderId}/invoice",
    response_model=SuccessResponse[InvoiceOut],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Invoice not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_order_invoice(
    request: Request,
    order_id: uuid.UUID = Path(alias="orderId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[InvoiceOut]:
    """Счёт по заказу: клиент — только свой заказ, менеджер — любой (§6)."""
    service = InvoiceService(db)
    try:
        invoice = await service.get_for_order(user, order_id)
        organization = await service.organization_for_invoice(invoice)
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc

    return SuccessResponse[InvoiceOut](
        data=invoice_out(invoice, organization=organization),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/invoices/{invoiceId}/download",
    response_class=Response,
    responses=problem_responses(
        {
            200: "Invoice PDF bytes (application/pdf)",
            401: "Authentication required",
            404: "Invoice not found",
            409: "Invoice PDF is not ready",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def download_invoice_pdf(
    invoice_id: uuid.UUID = Path(alias="invoiceId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отдаёт PDF счёта байтами (никогда presigned, §16 п.37).

    Нет доступа или нет счёта → 404 (не раскрываем существование чужого);
    ``pdf_status != READY`` → 409; хранилище недоступно → 502.
    """
    service = InvoiceService(db)
    try:
        invoice = await service.invoice_for_download(user, invoice_id)
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc

    if invoice.pdf_status != InvoicePdfStatus.READY or invoice.pdf_file_asset_id is None:
        raise V2ProblemError(
            code=InvoicePdfNotReadyError.code,
            status=InvoicePdfNotReadyError.status_code,
            title=InvoicePdfNotReadyError.title,
            detail=f"PDF счёта {invoice.number} ещё не готов",
        )

    asset = await db.get(FileAsset, invoice.pdf_file_asset_id)
    if asset is None or asset.type != FileAssetType.INVOICE_PDF:
        raise V2ProblemError(
            code="INVOICE_NOT_FOUND",
            status=status.HTTP_404_NOT_FOUND,
            title="Счёт не найден",
            detail="Файл счёта не найден в архиве",
        )

    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_pdfs, asset.s3_key
        )
    except storage.ObjectNotFound as exc:
        raise V2ProblemError(
            code="INVOICE_NOT_FOUND",
            status=status.HTTP_404_NOT_FOUND,
            title="Счёт не найден",
            detail="Файл счёта отсутствует в хранилище",
        ) from exc
    except storage.StorageError as exc:
        raise V2ProblemError(
            code="STORAGE_UNAVAILABLE",
            status=status.HTTP_502_BAD_GATEWAY,
            title="Хранилище недоступно",
            detail="Не удалось прочитать PDF счёта",
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
