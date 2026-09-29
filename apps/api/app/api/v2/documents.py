"""API v2 документы на товар: сертификаты и datasheets (§16 п.38).

Загрузка/удаление — MANAGER (RBAC ``require_role``, §11); чтение — любой
авторизованный в рамках карточки товара: блок ``documents[]`` приходит в
product detail (v2 ``catalog.py``), скачивание — байтами, по паттерну
``media.py`` (не presigned: внешний S3-хост обслуживается по http и режется
браузером как mixed content, §16 п.37).

Ключи S3 наружу не выдаются; документ должен принадлежать товару или его
серии, иначе 404. Просроченные документы (``valid_until < today``) не
скрываются — они приходят с ``isExpired: true``.
"""
from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import V2ProblemError, problem_responses, request_id_for
from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import FileAssetType, UserRole
from app.models.user import User
from app.repositories import catalog as repo
from app.repositories import file_assets as file_assets_repo
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.schemas.v2.documents import DocumentScope, ProductDocument
from app.services import file_assets as file_assets_service
from app.services import storage

router = APIRouter(tags=["catalog", "manager:documents"])


def _problem(status_code: int, *, code: str, title: str, detail: str) -> V2ProblemError:
    return V2ProblemError(code=code, status=status_code, title=title, detail=detail)


def _validated_idempotency_key(value: str | None) -> str | None:
    """Опциональный ключ повтора — тот же формат, что у заказов v2."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255 or any(ord(c) < 33 for c in normalized):
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            title="Ошибка валидации",
            detail="Idempotency-Key должен содержать от 1 до 255 допустимых символов",
        )
    return normalized


def _content_disposition(filename: str) -> str:
    """attachment с UTF-8 именем: ASCII-фолбэк + RFC 5987 filename*."""
    ascii_fallback = (
        filename.encode("ascii", "ignore").decode("ascii").strip() or "document.pdf"
    )
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


async def _upload_document(
    request: Request,
    db: AsyncSession,
    idempotency_key: str | None,
    *,
    upload: UploadFile,
    type: FileAssetType,
    valid_until_raw: str | None,
    scope: DocumentScope,
    target_id: uuid.UUID,
) -> SuccessResponse[ProductDocument]:
    """Общая реализация загрузки для товара и серии (контракт совпадает)."""
    _validated_idempotency_key(idempotency_key)
    try:
        valid_until = file_assets_service.validate_valid_until(valid_until_raw)
        asset = await file_assets_service.upload_product_document(
            db,
            upload=upload,
            type=type,
            valid_until=valid_until,
            product_id=target_id if scope == "product" else None,
            series_id=target_id if scope == "series" else None,
        )
    except storage.StorageError as exc:
        raise _problem(
            status.HTTP_502_BAD_GATEWAY,
            code="STORAGE_UNAVAILABLE",
            title="Хранилище недоступно",
            detail=str(exc),
        ) from exc
    try:
        await db.commit()
    except Exception:
        # Коммит принадлежит роутеру (§4); S3 чистится, если запись не легла.
        await db.rollback()
        await file_assets_service.cleanup_uncommitted_upload(db, asset)
        raise
    return SuccessResponse[ProductDocument](
        data=ProductDocument.from_asset(asset, scope=scope),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/manager/products/{productId}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ProductDocument],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Product not found",
            413: "File too large",
            415: "Not a PDF",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def upload_product_document(
    request: Request,
    product_id: uuid.UUID = Path(alias="productId"),
    file: UploadFile = File(..., description="PDF (magic-bytes %PDF, лимит files_max_mb)"),
    type: FileAssetType = Form(description="CERTIFICATE | DATASHEET"),
    valid_until: str | None = Form(
        default=None, description="Срок действия, YYYY-MM-DD (прошедшая дата допустима)"
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ProductDocument]:
    """Загрузить PDF-документ товара (сертификат/datasheet), §16 п.38.

    Менеджеру разрешено вешать документ и на архивный товар — обычную
    карточку он уже не увидит, но документ в архиве останется (SET NULL
    при удалении товара, §10).
    """
    if await repo.get_product_by_id(db, product_id) is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Товар не найден",
            detail="Товар не найден",
        )
    return await _upload_document(
        request,
        db,
        idempotency_key,
        upload=file,
        type=type,
        valid_until_raw=valid_until,
        scope="product",
        target_id=product_id,
    )


@router.post(
    "/manager/series/{seriesId}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ProductDocument],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Series not found",
            413: "File too large",
            415: "Not a PDF",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def upload_series_document(
    request: Request,
    series_id: uuid.UUID = Path(alias="seriesId"),
    file: UploadFile = File(..., description="PDF (magic-bytes %PDF, лимит files_max_mb)"),
    type: FileAssetType = Form(description="CERTIFICATE | DATASHEET"),
    valid_until: str | None = Form(
        default=None, description="Срок действия, YYYY-MM-DD (прошедшая дата допустима)"
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ProductDocument]:
    """Загрузить PDF-документ серии — наследуется всеми товарами серии."""
    if await repo.get_series(db, series_id) is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Серия не найдена",
            detail="Серия не найдена",
        )
    return await _upload_document(
        request,
        db,
        idempotency_key,
        upload=file,
        type=type,
        valid_until_raw=valid_until,
        scope="series",
        target_id=series_id,
    )


@router.delete(
    "/manager/documents/{documentId}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Document not found",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def delete_product_document(
    document_id: uuid.UUID = Path(alias="documentId"),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удалить документ (исправление ошибок): сначала S3, затем запись.

    Удалять здесь можно только документы товара/серии; остальной файловый
    архив удаляется через ``DELETE /api/v1/manager/files/{id}`` (§16 п.18).
    """
    row = await file_assets_repo.get_file_asset(db, document_id)
    asset = row[0] if row is not None else None
    if asset is None or asset.type not in file_assets_repo.PRODUCT_DOCUMENT_TYPES:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Документ не найден",
            detail="Документ не найден",
        )
    try:
        await file_assets_service.delete_asset(db, asset)
    except storage.StorageError as exc:
        raise _problem(
            status.HTTP_502_BAD_GATEWAY,
            code="STORAGE_UNAVAILABLE",
            title="Хранилище недоступно",
            detail=str(exc),
        ) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/catalog/products/{productId}/documents/{documentId}/download",
    response_class=Response,
    responses=problem_responses(
        {
            200: "Document bytes (application/pdf)",
            401: "Authentication required",
            404: "Product or document not found",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def download_product_document(
    product_id: uuid.UUID = Path(alias="productId"),
    document_id: uuid.UUID = Path(alias="documentId"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отдаёт байты PDF-документа товара/его серии (не presigned, §16 п.37).

    Товар — по правилам видимости карточки; документ, привязанный к другому
    товару/серии, неотличим от несуществующего — 404 (не раскрываем
    существование чужих файлов).
    """
    product = await repo.get_visible_by_id(db, product_id)
    if product is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Товар не найден",
            detail="Товар не найден",
        )
    document = await file_assets_repo.get_product_document(
        db,
        document_id=document_id,
        product_id=product.id,
        series_id=product.series_id,
    )
    if document is None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Документ не найден",
            detail="Документ не найден",
        )
    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_pdfs, document.s3_key
        )
    except storage.ObjectNotFound as exc:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            title="Документ не найден",
            detail="Файл документа отсутствует в хранилище",
        ) from exc
    except storage.StorageError as exc:
        raise _problem(
            status.HTTP_502_BAD_GATEWAY,
            code="STORAGE_UNAVAILABLE",
            title="Хранилище недоступно",
            detail="Не удалось прочитать документ",
        ) from exc
    return Response(
        content=data,
        media_type=document.content_type or "application/pdf",
        headers={
            "Content-Disposition": _content_disposition(document.filename_display),
            # Авторизованный ресурс: ключи неизменяемы, но документ могут
            # удалить — не объявляем immutable, как у фото.
            "Cache-Control": "private, max-age=3600",
        },
    )


__all__ = ["router"]
