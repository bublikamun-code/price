"""Файловый архив для менеджера: ``/api/v1/manager/files``.

См. ARCHITECTURE_PLAN.md §6 (контракт), §10 (S3), §16 п.18.

Эндпоинты:
  * ``POST   /manager/files``       — multipart-загрузка файла в архив;
  * ``GET    /manager/files``       — все записи + фильтры type/brand_id/visibility;
  * ``DELETE /manager/files/{id}``  — 204: сначала объект S3, затем запись БД.

Все эндпоинты требуют роль ``MANAGER`` (RBAC, §11). Валидация/S3 —
``services/file_assets``; роутер мапит ``StorageError`` → 502 и коммитит.
"""
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.catalog import Brand
from app.models.enums import FileAssetType, FileVisibility, UserRole
from app.models.user import User
from app.repositories import file_assets as file_assets_repo
from app.repositories.catalog import get_brand
from app.schemas import MetaPage
from app.schemas.file import FileAssetOut, FileAssetPage
from app.services import file_assets as file_assets_service
from app.services import storage

router = APIRouter(prefix="/files", tags=["manager:files"])


@router.post("", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(..., description="PDF-каталог / спец-CSV / ZIP (до 200 МБ)"),
    type: FileAssetType = Form(description="BRAND_PDF | CUSTOM_CSV | OTHER"),
    visibility: FileVisibility = Form(
        default=FileVisibility.AUTHED,
        description="PUBLIC | AUTHED | MANAGER_ONLY (по умолчанию AUTHED)",
    ),
    brand_id: uuid.UUID | None = Form(default=None, description="Бренд (опц.)"),
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> FileAssetOut:
    """Загрузить файл в архив (§16 п.18).

    Здесь — проверка ``brand_id``; валидация содержимого и S3 —
    ``services/file_assets.upload_asset`` (415/413/422 поднимает сервис,
    ``StorageError`` → 502).
    """
    brand: Brand | None = None
    if brand_id is not None:
        brand = await get_brand(db, brand_id)
        if brand is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Бренд не найден"
            )
    try:
        asset = await file_assets_service.upload_asset(
            db, upload=file, type=type, visibility=visibility, brand_id=brand_id
        )
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    try:
        await db.commit()
    except Exception:
        # Коммит принадлежит роутеру (§4), но S3 очищается только после отката
        # и проверки, что запись всё-таки не появилась в БД.
        await db.rollback()
        await file_assets_service.cleanup_uncommitted_upload(db, asset)
        raise
    return FileAssetOut.from_asset(
        asset, brand_name=brand.name if brand is not None else None
    )


@router.get("", response_model=FileAssetPage)
async def list_manager_files(
    type: FileAssetType | None = Query(default=None, description="Фильтр по типу"),
    brand_id: uuid.UUID | None = Query(default=None, description="Фильтр по бренду"),
    visibility: FileVisibility | None = Query(
        default=None, description="Фильтр по видимости"
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> FileAssetPage:
    """Все записи архива (§16 п.18) — включая MANAGER_ONLY."""
    visibilities = [visibility] if visibility is not None else None
    filters = file_assets_repo.FileAssetFilters(
        type=type, brand_id=brand_id, visibilities=visibilities
    )
    rows, total = await file_assets_repo.fetch_file_assets(
        db, filters=filters, limit=per_page, offset=(page - 1) * per_page
    )
    return FileAssetPage(
        data=[FileAssetOut.from_asset(row[0], brand_name=row[1]) for row in rows],
        meta=MetaPage(page=page, per_page=per_page, total=total),
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> None:
    """Удалить файл (§16 п.18): сначала объект S3, затем запись БД → 204.

    ``StorageError`` → 502, запись БД не трогается.
    """
    row = await file_assets_repo.get_file_asset(db, file_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден"
        )
    try:
        await file_assets_service.delete_asset(db, row[0])
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    await db.commit()
