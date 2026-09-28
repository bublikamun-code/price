"""API v2 media: стабильный id → байты изображения (§16 п.37).

Клиент кэширует картинку по ``mediaId``: ``url`` стабилен между вызовами, хотя
внутри каждый раз читается свежий объект.

Раньше эндпоинт отдавал 307 на presigned-URL, но внешний S3-хост доступен по
http, а портал работает по https — браузер режет такой редирект как mixed
content, ``<img>`` ловит ``error``, и в каталоге вместо фото встаёт заглушка.
Поэтому байты отдаёт сам API, как это уже делает публичная витрина v1
(``GET /api/v1/public/photo``). Плата — трафик картинок идёт через API.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.v2.errors import V2ProblemError, problem_responses
from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services import media as media_service
from app.services import storage

router = APIRouter(prefix="/media", tags=["media"])


@router.get(
    "/{mediaId}",
    response_class=Response,
    responses=problem_responses(
        {
            200: "Image bytes (image/webp)",
            401: "Authentication required",
            404: "Media not found",
            422: "Validation error",
            502: "Storage unavailable",
        }
    ),
)
async def get_media(
    media_id: uuid.UUID = Path(alias="mediaId"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отдаёт изображение каталога по стабильному mediaId.

    Объекта нет в бакете (ключ остался в реестре, фото удалили) → 404, как и
    неизвестный id; хранилище недоступно → 502.
    """
    asset = await media_service.get_asset(db, media_id)
    if asset is None:
        raise V2ProblemError(
            code="MEDIA_NOT_FOUND",
            status=404,
            title="Ресурс не найден",
            detail="Изображение не найдено",
        )
    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_photos, asset.s3_key
        )
    except storage.ObjectNotFound as exc:
        raise V2ProblemError(
            code="MEDIA_NOT_FOUND",
            status=404,
            title="Ресурс не найден",
            detail="Изображение не найдено",
        ) from exc
    except storage.StorageError as exc:
        raise V2ProblemError(
            code="STORAGE_UNAVAILABLE",
            status=502,
            title="Хранилище недоступно",
            detail="Не удалось прочитать изображение",
        ) from exc
    return Response(
        content=data,
        media_type=asset.mime_type or storage.photo_media_type(asset.s3_key),
        # Эндпоинт авторизованный → ассет приватный. Ключи неизменяемы, так что
        # клиент не должен переспрашивать картинку на каждом касании фильтров.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


__all__ = ["router"]
