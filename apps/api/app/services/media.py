"""Реестр изображений каталога и выдача стабильных media-ссылок (§16 п.37).

Зачем он нужен: presigned-URL живёт 5 минут и не может быть ключом кэша
ImageCache — при смене подписи нативный клиент скачал бы картинку заново и
заливал бы кэш дубликатами. Поэтому наружу отдаётся ``/api/v2/media/{mediaId}``,
где ``mediaId`` детерминирован и переживает любой рестарт, а сам S3-ключ остаётся
на сервере (docs/NATIVE_API_CONTRACT.md §6.1).

Соглашение о геометрии берётся у загрузчика фото (services/manager_catalog.py):
large — 1200×1200, ``_thumb`` — 400×400, формат webp.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ProductPhoto, Series
from app.models.file import MediaAsset

# Фиксированный namespace: смена константы сделала бы все ранее выданные mediaId
# нерезолвируемыми, поэтому значение — часть контракта, а не настройка.
MEDIA_NAMESPACE = uuid.UUID("6f2c4a1e-7b3d-4c58-9a10-5d8e2f4b6c93")

THUMB_SUFFIX = "_thumb.webp"
THUMB_SIZE = (400, 400)
LARGE_SIZE = (1200, 1200)
MIME_TYPE = "image/webp"

# S3-ключи фото живут только в бакете photos (§10).
PHOTO_KEY_PREFIXES = ("photos-series/", "photos-product/")


def media_id_for_key(s3_key: str) -> uuid.UUID:
    """Стабильный id изображения: uuid5 от S3-ключа.

    Детерминирован по построению — один и тот же ключ всегда даёт один и тот же
    id, в любом процессе и на любой машине. Поэтому backfill в миграции и
    выдача в рантайме не могут разойтись.
    """
    return uuid.uuid5(MEDIA_NAMESPACE, s3_key)


def dimensions_for_key(s3_key: str) -> tuple[int, int]:
    """Размеры по конвенции загрузчика: ``_thumb`` → 400×400, иначе 1200×1200."""
    return THUMB_SIZE if s3_key.endswith(THUMB_SUFFIX) else LARGE_SIZE


def is_photo_key(s3_key: str) -> bool:
    return s3_key.startswith(PHOTO_KEY_PREFIXES)


def media_ref(asset: MediaAsset) -> dict[str, object]:
    """Проекция реестра в v2-DTO. URL — стабильный v2-путь, не presigned."""
    return {
        "id": str(asset.id),
        "url": f"/api/v2/media/{asset.id}",
        "width": asset.width,
        "height": asset.height,
        "mime_type": asset.mime_type,
    }


def media_ref_for_key(s3_key: str) -> dict[str, object] | None:
    """Тот же DTO, вычисленный напрямую из ключа — для путей, где реестр ещё
    не обязателен (одиночное фото товара). Реестр нужен только чтобы отдать
    307 по id; здесь id выводится детерминированно и совпадёт с реестром."""
    if not s3_key:
        return None
    width, height = dimensions_for_key(s3_key)
    media_id = media_id_for_key(s3_key)
    return {
        "id": str(media_id),
        "url": f"/api/v2/media/{media_id}",
        "width": width,
        "height": height,
        "mime_type": MIME_TYPE,
    }


async def get_asset(db: AsyncSession, media_id: uuid.UUID) -> MediaAsset | None:
    return await db.get(MediaAsset, media_id)


async def register_key(
    db: AsyncSession, s3_key: str, *, commit: bool = False
) -> MediaAsset:
    """Регистрирует ключ в реестре (идемпотентно) и возвращает актив.

    Идемпотентность обязательна: один и тот же ключ может прийти и из фото
    серии, и из галереи товара, а перезалив фото не должен плодить дубли.
    """
    if not is_photo_key(s3_key):
        raise ValueError(f"не-photo S3-ключ: {s3_key!r}")
    media_id = media_id_for_key(s3_key)
    asset = await db.get(MediaAsset, media_id)
    if asset is not None:
        return asset
    width, height = dimensions_for_key(s3_key)
    asset = MediaAsset(
        id=media_id,
        s3_key=s3_key,
        width=width,
        height=height,
        mime_type=MIME_TYPE,
    )
    db.add(asset)
    if commit:
        await db.commit()
    return asset


async def register_existing_photo_keys(db: AsyncSession) -> int:
    """Backfill: регистрирует ключи, уже существующие в каталоге.

    Вызывается миграцией, поэтому должен быть идемпотентным и безопасным при
    повторном запуске: повторно добавленные ключи не создают новых строк.
    """
    keys: set[str] = set()
    for stmt in (
        select(Series.photo_key).where(Series.photo_key.isnot(None)),
        select(ProductPhoto.photo_key),
    ):
        keys.update(key for key in (await db.scalars(stmt)) if is_photo_key(key))
    added = 0
    for key in sorted(keys):
        if await db.get(MediaAsset, media_id_for_key(key)) is None:
            width, height = dimensions_for_key(key)
            db.add(
                MediaAsset(
                    id=media_id_for_key(key),
                    s3_key=key,
                    width=width,
                    height=height,
                    mime_type=MIME_TYPE,
                )
            )
            added += 1
    await db.commit()
    return added


__all__ = [
    "MEDIA_NAMESPACE",
    "dimensions_for_key",
    "get_asset",
    "is_photo_key",
    "media_id_for_key",
    "media_ref",
    "media_ref_for_key",
    "register_existing_photo_keys",
    "register_key",
]
