"""Реестр изображений каталога и выдача стабильных media-ссылок (§16 п.37).

Зачем он нужен: presigned-URL живёт 5 минут и не может быть ключом кэша
ImageCache — при смене подписи нативный клиент скачал бы картинку заново и
заливал бы кэш дубликатами. Поэтому наружу отдаётся ``/api/v2/media/{mediaId}``,
где ``mediaId`` детерминирован и переживает любой рестарт, а сам S3-ключ остаётся
на сервере (docs/NATIVE_API_CONTRACT.md §6.1).

Соглашение о геометрии берётся у загрузчика фото (services/manager_catalog.py):
large — 1200×1200, ``_thumb`` — 400×400, формат webp. Это БОКС, в который
фото вписывается без кропа и без увеличения, а не сам кадр: реальные размеры
изображения (например 800×600) меряются по объекту в S3 (см.
:func:`probe_dimensions`) и пишутся в реестр; конвенция остаётся фолбэком
для недоступного/нечитаемого объекта.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from io import BytesIO

from PIL import Image
from sqlalchemy import literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger
from app.models.banner import Banner
from app.models.catalog import ProductPhoto, Series
from app.models.file import MediaAsset
from app.services import storage

# Фиксированный namespace: смена константы сделала бы все ранее выданные mediaId
# нерезолвируемыми, поэтому значение — часть контракта, а не настройка.
MEDIA_NAMESPACE = uuid.UUID("6f2c4a1e-7b3d-4c58-9a10-5d8e2f4b6c93")

THUMB_SUFFIX = "_thumb.webp"
THUMB_SIZE = (400, 400)
LARGE_SIZE = (1200, 1200)
MIME_TYPE = "image/webp"

# Таймаут чтения объекта ради размеров: каталог не должен ждать S3 дольше,
# чем пользователь готов ждать картинку. Неуспех → откат на конвенцию.
PROBE_TIMEOUT_SECONDS = 5.0

# Кэш замеров: s3_key → фактические размеры либо None (замер не удался).
# Кэшируются и неудачи: иначе каждый повторный запрос каталога заново дёргал
# бы недоступное хранилище и ждал таймаут. Перемерить ключи заново можно
# скриптом app/scripts/media_dimensions.py (он работает в свежем процессе).
_dimension_cache: dict[str, tuple[int, int] | None] = {}

log = get_logger("app.services.media")

# S3-ключи фото живут только в бакете photos (§10).
PHOTO_KEY_PREFIXES = ("photos-series/", "photos-product/")

# Префикс ключей картинок баннеров в том же бакете (services/banner.py).
BANNER_KEY_PREFIX = "banners/"


def media_id_for_key(s3_key: str) -> uuid.UUID:
    """Стабильный id изображения: uuid5 от S3-ключа.

    Детерминирован по построению — один и тот же ключ всегда даёт один и тот же
    id, в любом процессе и на любой машине. Поэтому backfill в миграции и
    выдача в рантайме не могут разойтись.
    """
    return uuid.uuid5(MEDIA_NAMESPACE, s3_key)


def dimensions_for_key(s3_key: str) -> tuple[int, int]:
    """Размеры по конвенции загрузчика: ``_thumb`` → 400×400, иначе 1200×1200.

    Конвенция — это ФОЛБЭК, а не истина: реальный кадр может быть 800×600
    (загрузчик вписывает фото в бокс без кропа и без увеличения). Поэтому
    фактический размер меряется по самому объекту (см. :func:`probe_dimensions`),
    а эта функция используется, когда объект недоступен или не читается.
    """
    return THUMB_SIZE if s3_key.endswith(THUMB_SUFFIX) else LARGE_SIZE


def dimensions_from_bytes(data: bytes) -> tuple[int, int] | None:
    """Размеры изображения по его байтам (Pillow). None — не изображение.

    Заголовок читается лениво: ``Image.open`` разбирает только метаданные,
    полный кадр не декодируется.
    """
    try:
        with Image.open(BytesIO(data)) as img:
            return img.size
    except Exception:  # noqa: BLE001 — любой битый/неизвестный формат
        return None


async def probe_dimensions(s3_key: str) -> tuple[int, int] | None:
    """Фактические размеры объекта из S3. None — недоступен/нечитаем/не картинка.

    Единственный источник истины о геометрии кадра: конвенция загрузчика
    (1200×1200) описывает БОКС, а не сам кадр.

    Объект скачивается целиком: у Pillow нет «частичного» разбора webp —
    заголовок кадра лежит в начале файла, но библиотека требует весь буфер.
    Чтение синхронное (boto3), поэтому уходит в threadpool, а сверху стоит
    таймаут: недоступное хранилище не должно подвешивать каталог.
    """
    # None в кэше — это «замер не удался», а не «ключа нет»: различаем именно так,
    # иначе недоступное хранилище дёргалось бы на каждом запросе каталога.
    if s3_key in _dimension_cache:
        return _dimension_cache[s3_key]
    try:
        raw = await asyncio.wait_for(
            run_in_threadpool(
                storage.get_object_bytes, settings.s3_bucket_photos, s3_key
            ),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (storage.StorageError, asyncio.TimeoutError, OSError):
        log.warning("media.dimensions_probe_failed", s3_key=s3_key)
        _dimension_cache[s3_key] = None
        return None
    size = dimensions_from_bytes(raw)
    if size is None:
        log.warning("media.dimensions_not_an_image", s3_key=s3_key)
        _dimension_cache[s3_key] = None
        return None
    _dimension_cache[s3_key] = size
    return size


async def resolve_dimensions(s3_key: str) -> tuple[int, int]:
    """Фактические размеры объекта, а при неудаче — конвенция загрузчика."""
    probed = await probe_dimensions(s3_key)
    return probed if probed is not None else dimensions_for_key(s3_key)


async def _measure_dimensions(
    sem: asyncio.Semaphore, s3_key: str
) -> tuple[int, int]:
    """Замер под семафором: ограничиваем число параллельных чтений из S3."""
    async with sem:
        return await resolve_dimensions(s3_key)


def is_photo_key(s3_key: str | None) -> bool:
    """True, если значение — S3-ключ фото каталога (у товара фото может не быть)."""
    if not s3_key:
        return False
    return s3_key.startswith(PHOTO_KEY_PREFIXES)


def thumb_key_for(s3_key: str) -> str:
    """Ключ thumb-варианта по конвенции загрузчика (§16 п.17).

    ``photos-series/a.webp`` → ``photos-series/a_thumb.webp``. Ключ без ``.webp``
    или уже-thumb возвращается как есть: вариант выводится заменой суффикса,
    для него просто нет другого расположения (зеркалит services/public_catalog.py).

    Заменяется только ПОСЛЕДНЕЕ ``.webp`` (``str.replace`` заменял все вхождения
    и ломал ключ вида ``a.webp.backup.webp``).
    """
    if s3_key.endswith(".webp") and not s3_key.endswith(THUMB_SUFFIX):
        return s3_key[: -len(".webp")] + THUMB_SUFFIX
    return s3_key


def media_ref(asset: MediaAsset) -> dict[str, object]:
    """Проекция реестра в v2-DTO. URL — стабильный v2-путь, не presigned."""
    return {
        "id": str(asset.id),
        "url": f"/api/v2/media/{asset.id}",
        "width": asset.width,
        "height": asset.height,
        "mime_type": asset.mime_type,
    }


def media_ref_for_key(
    s3_key: str, *, thumb: bool = False
) -> dict[str, object] | None:
    """Тот же DTO, вычисленный напрямую из ключа — для путей, где реестр ещё
    не обязателен (одиночное фото товара). Реестр нужен только чтобы отдать
    307 по id; здесь id выводится детерминированно и совпадёт с реестром.

    ``thumb=True`` — ссылка на миниатюру: URL несёт ``?size=thumb`` (байты
    отдаёт эндпоинт ключом ``_thumb``, см. api/v2/media.py), геометрия —
    400×400 по конвенции, хотя в БД лежит large-ключ.

    Геометрия здесь ВСЕГДА по конвенции: функция синхронная и не ходит в БД,
    а фактические размеры живут в реестре (``MediaAsset.width/height``) и
    отдаются оттуда через :func:`media_ref`. Чтобы не отдавать клиенту
    придуманные числа, здесь честная конвенция — она совпадает с реальностью
    для квадратных кадров и расходится для остальных (см. L12).
    """
    if not s3_key:
        return None
    width, height = THUMB_SIZE if thumb else dimensions_for_key(s3_key)
    media_id = media_id_for_key(s3_key)
    url = f"/api/v2/media/{media_id}"
    if thumb:
        url += "?size=thumb"
    return {
        "id": str(media_id),
        "url": url,
        "width": width,
        "height": height,
        "mime_type": MIME_TYPE,
    }


async def get_asset(db: AsyncSession, media_id: uuid.UUID) -> MediaAsset | None:
    return await db.get(MediaAsset, media_id)


async def is_registered(db: AsyncSession, s3_key: str | None) -> bool:
    """Есть ли ключ в реестре медиа (фото каталога).

    Реестр — источник истины для «этот объект вообще известен системе».
    Выдача фото по сырому ключу без такой проверки означала бы fail-open:
    любой объект бакета photos отдавался бы клиенту, минуя visibility.
    """
    if not is_photo_key(s3_key):
        return False
    found = await db.scalar(
        select(MediaAsset.id).where(MediaAsset.s3_key == s3_key).limit(1)
    )
    return found is not None


def key_variants(s3_key: str) -> tuple[str, ...]:
    """Ключ и его thumb-«двойник» по конвенции §16 п.17.

    Реестры хранят base-ключ (``photos-series/a.webp``), а клиент по
    конвенции запрашивает миниатюру (``photos-series/a_thumb.webp``) — и
    наоборот, зарегистрированным может оказаться уже thumb-ключ. Если
    системе принадлежит один из вариантов, принадлежит и второй: это один
    и тот же объект каталога, просто в другом размере.
    """
    if s3_key.endswith(THUMB_SUFFIX):
        base = s3_key[: -len(THUMB_SUFFIX)] + ".webp"
        return (s3_key, base)
    return (s3_key, thumb_key_for(s3_key))


async def is_known_photo_key(db: AsyncSession, s3_key: str | None) -> bool:
    """Известен ли ключ системе — по любому из реестров.

    Ключ может прийти из разных мест: реестр медиа (§16 п.37), таблица
    баннеров, фото серии или галереи товара. Отдавать можно только то, что
    системе принадлежит: иначе клиент получил бы любой объект бакета photos
    мимо проверки видимости (fail-open).

    Проверяются оба варианта ключа (base и thumb, см. :func:`key_variants`):
    иначе миниатюра известного фото серии считалась бы «чужой» и картинка
    не отдавалась бы вовсе — при том, что объект системе принадлежит.
    """
    if not s3_key:
        return False
    if s3_key.startswith(BANNER_KEY_PREFIX):
        banner = await db.scalar(
            select(Banner.id).where(Banner.image_key == s3_key).limit(1)
        )
        return banner is not None
    for variant in key_variants(s3_key):
        if await is_registered(db, variant):
            return True
        found = await db.scalar(
            select(literal(1))
            .where(
                or_(
                    select(Series.id).where(Series.photo_key == variant).exists(),
                    select(ProductPhoto.id)
                    .where(ProductPhoto.photo_key == variant)
                    .exists(),
                )
            )
            .limit(1)
        )
        if found is not None:
            return True
    return False


async def register_key(
    db: AsyncSession,
    s3_key: str,
    *,
    commit: bool = False,
    dimensions: tuple[int, int] | None = None,
) -> MediaAsset:
    """Регистрирует ключ в реестре (идемпотентно) и возвращает актив.

    Идемпотентность обязательна: один и тот же ключ может прийти и из фото
    серии, и из галереи товара, а перезалив фото не должен плодить дубли.

    Размеры — фактические (меряются по объекту в S3); если объект
    недоступен, остаётся конвенция загрузчика. ``dimensions`` позволяет
    передать уже известный размер (загрузчик знает его после ресайза) —
    тогда лишнего чтения из S3 не будет.
    """
    if not is_photo_key(s3_key):
        raise ValueError(f"не-photo S3-ключ: {s3_key!r}")
    media_id = media_id_for_key(s3_key)
    asset = await db.get(MediaAsset, media_id)
    if asset is not None:
        return asset
    if dimensions is not None:
        width, height = dimensions
    else:
        width, height = await resolve_dimensions(s3_key)
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


async def ensure_registered(db: AsyncSession, keys: Iterable[str]) -> int:
    """Зарегистрировать в реестре недостающие ключи фото (идемпотентно).

    Реестр нужен, чтобы отдать картинку по стабильному id (``/api/v2/media/{id}``):
    id — это uuid5 от S3-ключа, и «развернуть» его обратно в ключ нельзя. Ключи
    попадают в каталог разными путями (ZIP с фото, загрузка менеджером, скрипты
    наполнения, ручные правки), и любой путь, забывший про реестр, даёт 404 на
    карточке товара: фото лежит в бакете, но по выданному id не находится.

    Поэтому каталог регистрирует недостающие ключи сам. Возвращает число
    добавленных строк (0 — всё уже было зарегистрировано).
    """
    photo_keys = {key for key in keys if is_photo_key(key)}
    if not photo_keys:
        return 0
    ids = {media_id_for_key(key): key for key in photo_keys}
    existing = set(
        (
            await db.scalars(
                select(MediaAsset.id).where(MediaAsset.id.in_(list(ids)))
            )
        ).all()
    )
    missing = [(mid, key) for mid, key in ids.items() if mid not in existing]
    if not missing:
        return 0
    # Фактические размеры меряются по объектам; недоступный объект даёт
    # конвенцию. Замеры идут параллельно, но ограниченно: реестр пополняется
    # в рантайме (каталог), и пачка объектов не должна блокировать запрос.
    sem = asyncio.Semaphore(4)
    measured = await asyncio.gather(
        *(_measure_dimensions(sem, key) for _, key in missing)
    )
    rows = [
        {
            "id": mid,
            "s3_key": key,
            "width": size[0],
            "height": size[1],
            "mime_type": MIME_TYPE,
        }
        for (mid, key), size in zip(missing, measured, strict=True)
    ]
    # ON CONFLICT DO NOTHING: гонка двух параллельных каталогов не должна
    # ронять запрос (уникальны и id, и s3_key).
    result = await db.execute(
        pg_insert(MediaAsset.__table__).values(rows).on_conflict_do_nothing()
    )
    await db.commit()
    return int(result.rowcount or 0)


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
            width, height = await resolve_dimensions(key)
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
    "BANNER_KEY_PREFIX",
    "MEDIA_NAMESPACE",
    "dimensions_for_key",
    "dimensions_from_bytes",
    "ensure_registered",
    "get_asset",
    "is_known_photo_key",
    "is_photo_key",
    "is_registered",
    "media_id_for_key",
    "media_ref",
    "media_ref_for_key",
    "probe_dimensions",
    "register_existing_photo_keys",
    "register_key",
    "resolve_dimensions",
    "thumb_key_for",
]
