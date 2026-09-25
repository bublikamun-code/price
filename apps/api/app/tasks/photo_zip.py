"""Обработка ZIP с фото серий (Celery). См. ARCHITECTURE_PLAN.md §10, §16 п.17.

Контракт:
  Вход:  ``job_id`` — стейт в Redis ``photozip:job:{job_id}`` (QUEUED),
         ZIP уже в S3 ``tmp-uploads/photo-zip/{job_id}.zip``.
  Шаги:
    1. скачать ZIP из S3;
    2. проверить лимиты по заголовкам ДО чтения содержимого (zip-bomb guard,
       §16 п.17): суммарно ≤500 МБ распакованных данных, ≤2000 файлов,
       один файл ≤50 МБ; нарушение → FAILED с сообщением;
    3. для каждого jpg/jpeg/png/webp: Pillow → webp large (fit 1200×1200)
       и thumb (fit 400×400), quality 82 → S3 ``photos-series/``;
    4. матчинг к сериям: нормализованный stem (lower, ``_``/пробел → ``-``)
       == slug серии (``_slugify(series.name)``), затем — совпадение имени
       файла с «сырым» ``series.photo_key`` из CSV ``series_photo`` (§7);
       unmatched-фото всё равно заливаются;
    5. matched серия: ``photo_key`` = ключ large (commit);
    6. статусы QUEUED → RUNNING → DONE (files/matched/unmatched/errors ≤50),
       после commit — инвалидация кэша каталога (фото — часть карточек).

Идемпотентность/надёжность — по образцу ``tasks/export_catalog.py``: слепой
авто-ретрай отключён (``autoretry_for=()``), критическая ошибка фиксирует
FAILED и пишется в лог, не роняя worker.
"""
from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from pathlib import PurePosixPath

from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.catalog import Series
from app.repositories.catalog import PHOTO_KEY_PREFIX, _slugify
from app.services import storage
from app.services.cache import CATALOG_TAG, FILTERS_TAG, invalidate_tags
from app.tasks._common import create_worker_db, mark_redis_job_failed
from app.workers import celery_app

log = get_logger("app.tasks.photo_zip")

# Лимиты распаковки (§16 п.17).
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # суммарный распакованный объём
MAX_FILES = 2000                            # файлов в архиве
MAX_FILE_SIZE = 50 * 1024 * 1024            # один файл

# Обрабатываемые форматы (регистронезависимо); прочие файлы — skipped.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

LARGE_SIZE = (1200, 1200)   # fit без кропа
THUMB_SIZE = (400, 400)
WEBP_QUALITY = 82
MAX_JOB_ERRORS = 50         # в стейт job'а пишем не больше

# Отдельный движок для Celery-задач (NullPool, по образцу import/export).
# Тесты подменяют ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine, _worker_session = create_worker_db()


class PhotoZipError(Exception):
    """ZIP непригоден целиком: повреждён или нарушены лимиты распаковки."""


@celery_app.task(bind=True, name="photo_zip", autoretry_for=())
def run_photo_zip(self, job_id: str, user_id: str, s3_key: str) -> dict:
    """Запуск обработки. Оборачивает async-пайплайн; ловит критические ошибки.

    ``user_id`` — владелец job'а (логирование/трассировка). Returns:
    ``{"job_id", "status", "files"?, "matched"?, "unmatched"?, "error"?}``.
    """
    try:
        return asyncio.run(_run_photo_zip(uuid.UUID(job_id), user_id, s3_key))
    except PhotoZipError as exc:  # ожидаемый guard — без стектрейса
        log.warning("photozip.rejected", job_id=job_id, error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception("photozip.crashed", job_id=job_id, error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _run_photo_zip(job_id: uuid.UUID, user_id: str, s3_key: str) -> dict:
    # Lazy-import: services.photo_zip тянет эту задачу наверх — избегаем
    # цикличности импортов на уровне модуля.
    from app.services.photo_zip import STATUS_DONE, STATUS_RUNNING, set_job_state

    await set_job_state(job_id, status=STATUS_RUNNING)

    try:
        data = storage.get_bytes(settings.s3_bucket_tmp, s3_key)
    finally:
        # Архив уже прочитан в память; очищаем временный объект и при ошибке
        # парсинга, чтобы ZIP-файлы не накапливались в tmp-бакете.
        try:
            storage.delete_object(settings.s3_bucket_tmp, s3_key)
        except storage.StorageError as exc:
            log.warning(
                "photozip.tmp_object_delete_failed",
                job_id=str(job_id),
                s3_key=s3_key,
                error=str(exc),
            )
    files = matched = unmatched = 0
    errors: list[str] = []

    with _open_zip(data) as zf:
        entries = _image_entries(zf)
        async with _worker_session() as db:
            by_slug, by_photo = _series_lookups(
                (await db.execute(select(Series))).scalars().all()
            )
            for info in entries:
                name = PurePosixPath(info.filename).name
                stem = _norm_stem(PurePosixPath(name).stem)
                try:
                    large, thumb = _process_image(_read_capped(zf, info, name))
                except PhotoZipError:
                    raise  # лимит нарушен фактически — весь job FAILED
                except Exception as exc:
                    # Битый/нечитаемый файл — фиксируем и идём дальше.
                    errors.append(f"{name}: не удалось обработать изображение ({exc})")
                    continue

                key_large = f"{PHOTO_KEY_PREFIX}{stem}.webp"
                key_thumb = f"{PHOTO_KEY_PREFIX}{stem}_thumb.webp"
                storage.upload_fileobj(
                    settings.s3_bucket_photos, key_large, io.BytesIO(large),
                    content_type="image/webp",
                )
                storage.upload_fileobj(
                    settings.s3_bucket_photos, key_thumb, io.BytesIO(thumb),
                    content_type="image/webp",
                )
                files += 1

                # Приоритет (§16 п.17): slug по имени серии, затем «сырое»
                # photo_key из CSV series_photo == имя файла с расширением.
                series = by_slug.get(stem) or by_photo.get(name)
                if series is not None:
                    series.photo_key = key_large
                    matched += 1
                else:
                    unmatched += 1
            await db.commit()

    await set_job_state(
        job_id, status=STATUS_DONE, files=files, matched=matched,
        unmatched=unmatched, errors=errors[:MAX_JOB_ERRORS],
    )
    # Фото появляются в карточках каталога — кэш карточек сбрасываем (fail-open).
    await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
    log.info("photozip.done", job_id=str(job_id), user_id=user_id, files=files,
             matched=matched, unmatched=unmatched, errors=len(errors))
    return {
        "job_id": str(job_id), "status": STATUS_DONE, "files": files,
        "matched": matched, "unmatched": unmatched,
    }


# ----------------------------- zip guards -----------------------------

def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        zf.infolist()  # форсируем чтение центрального каталога
        return zf
    except zipfile.BadZipFile as exc:
        raise PhotoZipError(f"ZIP-архив повреждён: {exc}") from exc


def _image_entries(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Записи-изображения после проверки лимитов по заголовкам (до чтения)."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise PhotoZipError(f"В архиве больше {MAX_FILES} файлов")
    total = sum(i.file_size for i in infos)
    if total > MAX_TOTAL_UNCOMPRESSED:
        raise PhotoZipError(
            f"Распакованный объём превышает лимит 500 МБ ({total // (1024 * 1024)} МБ)"
        )
    for i in infos:
        if i.file_size > MAX_FILE_SIZE:
            raise PhotoZipError(f"{i.filename}: файл больше 50 МБ")
    images = [i for i in infos if PurePosixPath(i.filename).suffix.lower()
              in IMAGE_EXTENSIONS]
    skipped = len(infos) - len(images)
    if skipped:
        log.info("photozip.skipped_non_images", count=skipped)
    return images


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo, name: str) -> bytes:
    """Читать запись с фактическим лимитом: заголовок ``file_size`` может врать."""
    with zf.open(info) as fh:
        data = fh.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise PhotoZipError(f"{name}: распакованный файл больше 50 МБ")
    return data


# ----------------------------- images -----------------------------

def _norm_stem(stem: str) -> str:
    """stem файла → нормализованный ключ: lower, ``_`` и пробел → ``-``."""
    return stem.lower().strip().replace("_", "-").replace(" ", "-")


def _process_image(raw: bytes) -> tuple[bytes, bytes]:
    """Pillow: large (fit 1200×1200) и thumb (fit 400×400), webp quality 82.

    ``thumbnail`` только уменьшает (без кропа и без увеличения). Обе
    производные строятся из исходника: ``convert("RGB")`` возвращает копию.
    """
    with Image.open(io.BytesIO(raw)) as img:
        large_img = img.convert("RGB")
        large_img.thumbnail(LARGE_SIZE)
        thumb_img = img.convert("RGB")
        thumb_img.thumbnail(THUMB_SIZE)
        return _to_webp(large_img), _to_webp(thumb_img)


def _to_webp(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()


# ----------------------------- series -----------------------------

def _series_lookups(
    all_series: list[Series],
) -> tuple[dict[str, Series], dict[str, Series]]:
    """Индексы серий: по «slug» (``_slugify(name)``) и по сырому ``photo_key``."""
    by_slug: dict[str, Series] = {}
    by_photo: dict[str, Series] = {}
    for s in all_series:
        by_slug.setdefault(_slugify(s.name), s)
        if s.photo_key and not s.photo_key.startswith(PHOTO_KEY_PREFIX):
            by_photo.setdefault(s.photo_key, s)
    return by_slug, by_photo


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    """Пометить job FAILED при критической ошибке (storage/неожиданное)."""
    await mark_redis_job_failed("app.services.photo_zip", job_id, message)
