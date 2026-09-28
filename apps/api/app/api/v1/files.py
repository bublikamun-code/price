"""Выдача файлов из S3: ``/api/v1/files/*``. См. ARCHITECTURE_PLAN.md §6, §10, §16 п.18.

Эндпоинты требуют авторизации (любая роль): файлы портала — не публичные.

  * ``GET /files`` — файловый архив (§16 п.18): CLIENT видит только
    ``visibility IN (PUBLIC, AUTHED)``, MANAGER — все записи; фильтры
    ``type`` / ``brand_id`` + пагинация §6;
  * ``GET /files/{id}/download`` — presigned-URL (TTL 5 мин); нет файла
    или недоступен по visibility → 404;
  * ``GET /files/photo?key=photos-series/...`` — фото серии/товара: байтами
    (§16 п.18). Редирект на presigned здесь не годится: внешний S3-хост
    отдаётся по http, сайт — по https, и браузер блокирует такой переход.
    Публичная витрина (``/public/photo``, api/v1/public.py) решает это так же.

Ключ фото валидируется: обязательный «голый» путь без схемы и без ``..``
(path traversal), иначе 400.
"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import FileAssetType, FileVisibility, UserRole
from app.models.file import FileAsset
from app.models.user import User
from app.repositories import file_assets as file_assets_repo
from app.schemas import MetaPage
from app.schemas.file import (
    FileAssetOut,
    FileAssetPage,
    FileDownloadOut,
    FileDownloadResponse,
)
from app.services import file_assets as file_assets_service
from app.services import storage

router = APIRouter(prefix="/files", tags=["files"])

# Ключ — путь внутри бакета: без схемы (http://, s3://…) и без «..».
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

# Что видит CLIENT в архиве (§16 п.18); MANAGER — всё.
_CLIENT_VISIBILITIES = (FileVisibility.PUBLIC, FileVisibility.AUTHED)


def _can_see(user: User, asset: FileAsset) -> bool:
    """Доступность файла по visibility (§16 п.18): MANAGER — все."""
    if user.role == UserRole.MANAGER:
        return True
    return asset.visibility in _CLIENT_VISIBILITIES


def _validate_photo_key(key: str) -> str:
    """Проверить S3-ключ фото (§16 п.17): путь без схемы, без ``..``, не пустой."""
    key = key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой ключ")
    if ".." in key or _SCHEME_RE.match(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый ключ файла"
        )
    return key


@router.get("", response_model=FileAssetPage)
async def list_files(
    type: FileAssetType | None = Query(default=None, description="Фильтр по типу файла"),
    brand_id: uuid.UUID | None = Query(default=None, description="Фильтр по бренду"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileAssetPage:
    """Файловый архив (§16 п.18): CLIENT — PUBLIC/AUTHED, MANAGER — все."""
    visibilities = None if user.role == UserRole.MANAGER else _CLIENT_VISIBILITIES
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


@router.get("/{file_id}/download", response_model=FileDownloadResponse)
async def download_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileDownloadResponse:
    """Presigned-URL на файл (TTL 5 мин, §16 п.18).

    Нет файла или недоступен по visibility → 404 (не раскрываем наличие).
    """
    row = await file_assets_repo.get_file_asset(db, file_id)
    if row is None or not _can_see(user, row[0]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден"
        )
    try:
        url = file_assets_service.issue_download_url(row[0])
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return FileDownloadResponse(
        data=FileDownloadOut(url=url, expires_in=settings.s3_presign_ttl_seconds)
    )


@router.get("/photo")
async def get_photo(
    key: str = Query(description="S3-ключ фото (например photos-series/serie-a.webp)"),
    _user: User = Depends(get_current_user),
) -> Response:
    """Фото серии/товара — байтами (§16 п.18).

    Раньше был 307 на presigned, но внешний S3-хост отдаётся по http, а сайт
    работает по https: браузер режет такой редирект как mixed content, и
    ``<img>`` ловит ``error`` вместо картинки. Публичная витрина давно решает
    это отдачей байтов из API (см. ``/public/photo``), здесь авторизованный
    клиент получает то же самое.

    Ключ валидируется ДО чтения: «голый» путь без схемы и без ``..`` — иначе
    400. Объекта нет → 404, хранилище недоступно → 502.
    """
    valid_key = _validate_photo_key(key)
    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_photos, valid_key
        )
    except storage.ObjectNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено"
        ) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Хранилище недоступно"
        ) from exc
    media_type = storage.photo_media_type(valid_key)
    return Response(
        content=data,
        media_type=media_type,
        # Эндпоинт авторизованный, поэтому ассет приватный: общий кэш не должен
        # отдавать его гостю. Ключи неизменяемы (uuid/hash в пути), immutability
        # исключает опрос на каждом касании фильтров.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
