"""Роутер брендов и серий менеджера (/api/v1/manager/brands, /series/{id}/photo).

См. §6, §16 п.20-3. CRUD брендов (slug стабилен при переименовании — ключи фото)
и загрузка фото серии (webp large+thumb, как photo-ZIP). Роль MANAGER (§11).
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.manager_catalog import (
    BrandCreateIn,
    BrandOut,
    BrandRenameIn,
    SeriesPhotoOut,
)
from app.services import storage
from app.services.manager_catalog import (
    ConflictError,
    InvalidImageError,
    ManagerCatalogService,
    NotFoundError,
)

router = APIRouter(tags=["manager:brands"])

# Лимиты фото серии (§16 п.20-3): формат и размер.
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
    """Прочитать файл в память с лимитом 20 МБ (фото серии небольшое)."""
    buf = bytearray()
    while chunk := await file.read(_READ_CHUNK):
        buf.extend(chunk)
        if len(buf) > _MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Файл превышает лимит 20 МБ",
            )
    return bytes(buf)


@router.get("/brands", response_model=list[BrandOut])
async def list_brands(
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> list[BrandOut]:
    """Бренды со счётчиками серий и не удалённых товаров, по имени."""
    return await ManagerCatalogService(db).list_brands()


@router.post("/brands", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(
    payload: BrandCreateIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> BrandOut:
    """Создать бренд; slug генерируется из имени, при коллизии — суффикс -2/-3."""
    try:
        return await ManagerCatalogService(db).create_brand(manager, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.patch("/brands/{brand_id}", response_model=BrandOut)
async def rename_brand(
    brand_id: uuid.UUID,
    payload: BrandRenameIn,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> BrandOut:
    """Переименовать бренд (slug не меняется — стабильные ключи фото)."""
    try:
        return await ManagerCatalogService(db).rename_brand(manager, brand_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    brand_id: uuid.UUID,
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удалить бренд; при наличии серий/товаров — 409 (FK и целостность каталога)."""
    try:
        await ManagerCatalogService(db).delete_brand(manager, brand_id)
    except ValueError as exc:
        raise _to_http(exc) from exc


@router.post("/series/{series_id}/photo", response_model=SeriesPhotoOut)
async def upload_series_photo(
    series_id: uuid.UUID,
    file: UploadFile = File(..., description="Фото серии (jpg/jpeg/png/webp, до 20 МБ)"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SeriesPhotoOut:
    """Загрузить фото серии: webp large+thumb в photos-series + photo_key."""
    name = (file.filename or "").lower()
    if not any(name.endswith(ext) for ext in _ALLOWED_IMAGE_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Допустимы только файлы: {', '.join(sorted(_ALLOWED_IMAGE_EXTENSIONS))}",
        )
    raw = await _read_capped(file)
    try:
        return await ManagerCatalogService(db).upload_series_photo(manager, series_id, raw)
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
