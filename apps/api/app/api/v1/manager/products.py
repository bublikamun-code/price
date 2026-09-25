"""Роутер товаров менеджера (/api/v1/manager/products). См. §6, §16 п.20-2.

Список с фильтрами (в отличие от клиентского каталога виден и ARCHIVED) и
точечный PATCH ручной цены/статуса; мутации пишут audit_log и инвалидируют
кэш каталога. Галерея доп. фото товара: POST/DELETE …/photos (§6).
Полный экспорт продукции в CSV (все характеристики + ссылки на фото):
POST /export, статус — GET /export/{job_id}. Все эндпоинты требуют
роль MANAGER (§11 RBAC).
"""
import io
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_role
from app.core.limiter import EXPORT_RATE_LIMIT, export_rate_key, limiter
from app.db.session import get_db
from app.models.enums import StockStatus, UserRole
from app.models.user import User
from app.schemas import MetaPage
from app.schemas.catalog import ExportJobOut, ExportStartOut
from app.schemas.manager_catalog import (
    ManagerProductPage,
    ManagerProductPatchIn,
    ManagerProductRead,
    ProductPhotoOut,
)
from app.services import product_export, storage
from app.services.manager_catalog import (
    ConflictError,
    InvalidImageError,
    ManagerCatalogService,
    NotFoundError,
)

router = APIRouter(prefix="/products", tags=["manager:products"])

# Лимиты фото товара (§6): формат и размер — как у фото серии (§16 п.20-3).
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_BYTES = 20 * 1024 * 1024
_READ_CHUNK = 1024 * 1024


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, ConflictError → 409, прочие ValueError → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


async def _read_capped(file: UploadFile) -> bytes:
    """Прочитать файл в память с лимитом 20 МБ (фото товара небольшое)."""
    buf = bytearray()
    while chunk := await file.read(_READ_CHUNK):
        buf.extend(chunk)
        if len(buf) > _MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Файл превышает лимит 20 МБ",
            )
    return bytes(buf)


@router.get("", response_model=ManagerProductPage)
async def list_products(
    q: str | None = Query(default=None, description="Поиск: артикул/наименование"),
    brand_id: uuid.UUID | None = Query(default=None),
    stock: StockStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagerProductPage:
    items, total = await ManagerCatalogService(db).list_products(
        q=q, brand_id=brand_id, stock=stock, page=page, per_page=per_page
    )
    return ManagerProductPage(data=items, meta=MetaPage(page=page, per_page=per_page, total=total))


@router.patch("/{product_id}", response_model=ManagerProductRead)
async def update_product(
    product_id: uuid.UUID,
    payload: ManagerProductPatchIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagerProductRead:
    """Ручная цена (``override_price``, null — сброс) и/или статус остатка."""
    try:
        return await ManagerCatalogService(db).update_product(manager, product_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.post(
    "/{product_id}/photos",
    response_model=ProductPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_photo(
    product_id: uuid.UUID,
    file: UploadFile = File(..., description="Фото товара (jpg/jpeg/png/webp, до 20 МБ)"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ProductPhotoOut:
    """Загрузить доп. фото товара: webp large+thumb в photos-product + запись в БД."""
    name = (file.filename or "").lower()
    if not any(name.endswith(ext) for ext in _ALLOWED_IMAGE_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Допустимы только файлы: {', '.join(sorted(_ALLOWED_IMAGE_EXTENSIONS))}",
        )
    raw = await _read_capped(file)
    try:
        return await ManagerCatalogService(db).upload_product_photo(manager, product_id, raw)
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.delete(
    "/{product_id}/photos/{photo_key:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_product_photo(
    product_id: uuid.UUID,
    photo_key: str,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удалить доп. фото товара (запись + объекты large/thumb из S3)."""
    try:
        await ManagerCatalogService(db).delete_product_photo(manager, product_id, photo_key)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.post(
    "/export",
    response_model=ExportStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(EXPORT_RATE_LIMIT, key_func=export_rate_key)
async def start_products_export(
    request: Request,
    manager: User = Depends(require_role(UserRole.MANAGER)),
) -> ExportStartOut:
    """Запустить полный экспорт продукции в CSV: все характеристики колонками
    (объединение ключей attributes) + ссылки на фото отдельными колонками.

    Без персональных цен — выгрузка менеджера (базовая и договорная цены).
    Файл собирает Celery-задача: статус — ``GET /export/{job_id}``.
    Лимит: 10 запусков/час на пользователя.
    """
    job_id = await product_export.start_full_export(user=manager)
    return ExportStartOut(job_id=job_id)


@router.get("/export/{job_id}", response_model=ExportJobOut)
async def get_products_export_job(
    job_id: uuid.UUID,
    manager: User = Depends(require_role(UserRole.MANAGER)),
) -> ExportJobOut:
    """Статус job экспорта (только владелец, чужой/несуществующий → 404).

    ``url`` — presigned-ссылка на файл в S3 (5 мин), отдаётся только при DONE.
    """
    state = await product_export.get_full_export_job(manager.id, job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Экспорт не найден"
        )
    url = None
    if state.get("status") == "DONE" and state.get("s3_key"):
        url = storage.presigned_get(settings.s3_bucket_exports, state["s3_key"])
    return ExportJobOut(
        job_id=state["job_id"],
        status=state["status"],
        format=state["format"],
        error=state.get("error"),
        url=url,
    )


@router.get("/export/{job_id}/download")
async def download_products_export(
    job_id: uuid.UUID,
    manager: User = Depends(require_role(UserRole.MANAGER)),
) -> StreamingResponse:
    """Прокси-скачивание экспорта из S3 (обходит проблему с presigned URL)."""
    state = await product_export.get_full_export_job(manager.id, job_id)
    if state is None or state.get("status") != "DONE" or not state.get("s3_key"):
        raise HTTPException(404, detail="Экспорт не найден или не готов")
    s3_key = state["s3_key"]
    filename = f"products-full-{job_id}.csv"
    try:
        body = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_exports, s3_key
        )
    except storage.StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
