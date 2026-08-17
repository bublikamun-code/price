"""Выдача файлов из S3: ``/api/v1/files/*``. См. ARCHITECTURE_PLAN.md §6, §10.

Эндпоинты требуют авторизации (любая роль): файлы портала — не публичные.

  * ``GET /files/photo?key=photos-series/...`` — фото серии: 307-редирект на
    presigned URL (5 мин, §16 п.17). Экономим bandwidth API: содержимое
    отдаёт MinIO, а не воркеры FastAPI.

Ключ валидируется: обязательный «голый» путь без схемы и без ``..``
(path traversal), иначе 400.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.deps import get_current_user
from app.models.user import User
from app.services import storage

router = APIRouter(prefix="/files", tags=["files"])

# Ключ — путь внутри бакета: без схемы (http://, s3://…) и без «..».
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


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


@router.get("/photo")
async def get_photo(
    key: str = Query(description="S3-ключ фото (например photos-series/serie-a.webp)"),
    _user: User = Depends(get_current_user),
) -> RedirectResponse:
    """Редирект 307 на presigned URL фото серии из бакета ``photos-series``."""
    valid_key = _validate_photo_key(key)
    try:
        url = storage.presigned_get(settings.s3_bucket_photos, valid_key)
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
