"""Use-case'ы файлового архива (§10, §16 п.18, §16 п.38).

  * ``upload_asset`` — приём файла менеджером: валидация (расширение,
    content-type, magic-bytes, размер — стримингом по чанкам, без
    буферизации в памяти, паттерн ``_validate_zip_stream`` из
    manager/prices), заливка в S3 ``pdf-catalogs`` стримингом и запись
    ``file_assets``;
  * ``upload_product_document`` — сертификат/datasheet товара или серии
    (§16 п.38): PDF-only, тот же конвейер валидации; запись получает
    ``product_id``/``series_id`` и ``valid_until``;
  * ``issue_download_url`` — presigned-URL (TTL 5 мин, §10);
  * ``delete_asset`` — сначала объект S3, затем запись БД (§16 п.18):
    при ``StorageError`` запись не трогается.

Ошибки валидации поднимаются как ``HTTPException`` (паттерн
manager/prices: 415/413/422 — HTTP-концерны). ``StorageError`` не
ловим — роутер мапит её в 502. Коммитит роутер (§4).
"""
import uuid
from datetime import date

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import FileAssetType, FileVisibility
from app.models.file import FileAsset
from app.repositories import file_assets as file_assets_repo
from app.services import storage

log = get_logger("app.services.file_assets")

_READ_CHUNK = 1024 * 1024

# Разрешённые расширения → content-type'ы (§16 п.18).
# ``application/octet-stream`` разрешён всем: браузеры часто так шлют файлы.
_ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".csv": {
        "application/csv",
        "application/octet-stream",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
    },
    ".zip": {
        "application/octet-stream",
        "application/x-zip-compressed",
        "application/zip",
    },
}

# magic-bytes (сигнатуры) по расширению; CSV — без magic (§16 п.18).
_MAGIC_PREFIXES: dict[str, bytes] = {".pdf": b"%PDF", ".zip": b"PK"}

_MAGIC_ERRORS = {
    ".pdf": "Файл не является корректным PDF",
    ".zip": "Файл не является ZIP-архивом",
}

# Срок действия документа: отсекаем только бессмыслицу (опечатки в годе).
# Дата в прошлом допустима — документ останется видимым с is_expired=true.
_VALID_UNTIL_MIN = date(2000, 1, 1)
_VALID_UNTIL_MAX = date(2100, 12, 31)


def _extension(filename: str) -> str:
    """Разрешённое расширение файла; иначе 415 (§16 п.18)."""
    name = (filename or "").lower()
    for ext in _ALLOWED_CONTENT_TYPES:
        if name.endswith(ext):
            return ext
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Допустимы только файлы: .pdf, .csv, .zip",
    )


def _validate_content_type(upload: UploadFile, *, ext: str) -> str:
    """Content-Type должен соответствовать расширению; иначе 415."""
    content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in _ALLOWED_CONTENT_TYPES[ext]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Неподдерживаемый Content-Type для {ext}",
        )
    return content_type


async def _validate_stream(upload: UploadFile, *, ext: str, max_bytes: int) -> int:
    """Потоковая валидация: размер ≤ ``max_bytes`` + magic-byты первого чанка.

    Читаем чанками из spool-файла Starlette — файл не материализуется
    в памяти (паттерн ``_validate_zip_stream``). Возвращает размер в байтах.
    """
    total = 0
    first: bytes | None = None
    while chunk := await upload.read(_READ_CHUNK):
        if first is None:
            first = chunk
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Файл превышает лимит {settings.files_max_mb} МБ",
            )
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл"
        )
    magic = _MAGIC_PREFIXES.get(ext)
    if magic is not None and not first.startswith(magic):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=_MAGIC_ERRORS[ext],
        )
    return total


async def upload_asset(
    db: AsyncSession,
    *,
    upload: UploadFile,
    type: FileAssetType,
    visibility: FileVisibility,
    brand_id: uuid.UUID | None,
) -> FileAsset:
    """Завалидировать и загрузить файл в архив (§16 п.18).

    Ключ — ``{type}/{uuid}{ext}`` в бакете ``pdf-catalogs``. S3-объект
    заливается ДО создания записи: при ``StorageError`` в БД ничего не
    меняется (нет записи, указывающей на несуществующий объект).
    """
    if type in (
        FileAssetType.PHOTO_ZIP,
        FileAssetType.CERTIFICATE,
        FileAssetType.DATASHEET,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{type.value} — тип с обязательной привязкой: загрузка через "
                "v2 manager documents (файл архива без товара/серии не имеет смысла)"
            ),
        )
    ext = _extension(upload.filename or "")
    content_type = _validate_content_type(upload, ext=ext)
    max_bytes = settings.files_max_mb * 1024 * 1024
    size_bytes = await _validate_stream(upload, ext=ext, max_bytes=max_bytes)

    key = f"{type.value.lower()}/{uuid.uuid4()}{ext}"
    await upload.seek(0)
    await run_in_threadpool(
        storage.upload_fileobj,
        settings.s3_bucket_pdfs,
        key,
        upload.file,
        content_type=content_type or "application/octet-stream",
    )
    try:
        return await file_assets_repo.create_file_asset(
            db,
            type=type,
            s3_key=key,
            filename_display=upload.filename or key,
            content_type=upload.content_type,
            size_bytes=size_bytes,
            brand_id=brand_id,
            visibility=visibility,
        )
    except Exception:
        # Flush не создал строку — уникальный ключ больше не на что опереться,
        # поэтому откатываем транзакцию и убираем новый S3-объект.
        await db.rollback()
        await _delete_uploaded_object(key, reason="db_flush_failed")
        raise


def validate_valid_until(raw: str | None) -> date | None:
    """``valid_until`` из формы → date; пустая строка → None (§16 п.38).

    Дата в прошлом не запрещена: документ останется видимым и будет помечен
    ``is_expired``. Отсекаем только бессмыслицу (опечатки в годе) и мусорный
    формат — иначе 422 (HTTP-концерн валидации, паттерн manager/prices).
    """
    if raw is None or not raw.strip():
        return None
    try:
        parsed = date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="valid_until должен быть датой в формате YYYY-MM-DD",
        ) from exc
    if not (_VALID_UNTIL_MIN <= parsed <= _VALID_UNTIL_MAX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "valid_until вне допустимого диапазона "
                f"({_VALID_UNTIL_MIN.isoformat()}..{_VALID_UNTIL_MAX.isoformat()})"
            ),
        )
    return parsed


async def upload_product_document(
    db: AsyncSession,
    *,
    upload: UploadFile,
    type: FileAssetType,
    valid_until: date | None,
    product_id: uuid.UUID | None = None,
    series_id: uuid.UUID | None = None,
) -> FileAsset:
    """Сертификат/datasheet товара или серии (§16 п.38).

    PDF-only: сертификат в JPEG или CSV-прайс в этот раздел не проходит —
    для них есть файловый архив (``upload_asset``). Привязка обязательна
    ровно одна: документ без товара/серии недостижим из карточки. S3-объект
    заливается ДО записи в БД (паттерн ``upload_asset``).
    """
    if type not in file_assets_repo.PRODUCT_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="type должен быть CERTIFICATE или DATASHEET",
        )
    if (product_id is None) == (series_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Документ привязывается к товару или к серии (ровно одна привязка)",
        )
    ext = _extension(upload.filename or "")
    if ext != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Документы на товар принимаются только в PDF",
        )
    content_type = _validate_content_type(upload, ext=ext)
    max_bytes = settings.files_max_mb * 1024 * 1024
    size_bytes = await _validate_stream(upload, ext=ext, max_bytes=max_bytes)

    key = f"{type.value.lower()}/{uuid.uuid4()}{ext}"
    await upload.seek(0)
    await run_in_threadpool(
        storage.upload_fileobj,
        settings.s3_bucket_pdfs,
        key,
        upload.file,
        content_type=content_type or "application/octet-stream",
    )
    try:
        return await file_assets_repo.create_file_asset(
            db,
            type=type,
            s3_key=key,
            filename_display=upload.filename or key,
            content_type=upload.content_type,
            size_bytes=size_bytes,
            brand_id=None,
            product_id=product_id,
            series_id=series_id,
            valid_until=valid_until,
            visibility=FileVisibility.AUTHED,
        )
    except Exception:
        await db.rollback()
        await _delete_uploaded_object(key, reason="db_flush_failed")
        raise


async def _delete_uploaded_object(key: str, *, reason: str) -> None:
    """Best-effort удаление объекта, созданного до записи в БД."""
    try:
        await run_in_threadpool(
            storage.delete_object, settings.s3_bucket_pdfs, key
        )
    except storage.StorageError as exc:
        # Исходная ошибка БД должна остаться основной; cleanup-ошибка попадает
        # в лог, чтобы осиротевший ключ можно было найти и удалить вручную.
        log.warning(
            "file_upload.s3_cleanup_failed",
            key=key,
            reason=reason,
            error=str(exc),
        )


async def cleanup_uncommitted_upload(db: AsyncSession, asset: FileAsset) -> None:
    """Удалить объект только если после неуспешного commit записи в БД нет."""
    try:
        persisted = await db.get(FileAsset, asset.id)
    except Exception as exc:
        # Неизвестный результат commit опасен для данных: не удаляем объект,
        # который уже может быть записан, но явно фиксируем невозможность проверки.
        log.exception(
            "file_upload.commit_state_unknown",
            asset_id=str(asset.id),
            s3_key=asset.s3_key,
            error=str(exc),
        )
        return
    if persisted is not None:
        return
    await _delete_uploaded_object(asset.s3_key, reason="db_commit_failed")


def issue_download_url(asset: FileAsset) -> str:
    """Presigned-URL на чтение файла (TTL 5 мин, §10).

    ``StorageError`` прокидывается наверх — роутер мапит в 502.
    """
    return storage.presigned_get(settings.s3_bucket_pdfs, asset.s3_key)


async def delete_asset(db: AsyncSession, asset: FileAsset) -> None:
    """Удалить файл: сначала объект S3, затем запись БД (§16 п.18).

    При ``StorageError`` запись БД не трогается (роутер → 502) —
    не остаётся записи без объекта в хранилище.
    """
    await run_in_threadpool(
        storage.delete_object, settings.s3_bucket_pdfs, asset.s3_key
    )
    await file_assets_repo.delete_file_asset(db, asset)
