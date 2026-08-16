"""Импорт прайс-листов менеджером: ``/api/v1/manager/prices/*``.

См. ARCHITECTURE_PLAN.md §6 (контракт), §7 (пайплайн), §17.2 (курс прайса).

Эндпоинты:
  * ``POST /import``          — multipart-загрузка CSV → запуск Celery-задачи.
  * ``GET  /versions``        — история импортов (пагинация).
  * ``GET  /versions/{id}``   — карточка версии (статус, счётчики, курс).
  * ``GET  /versions/{id}/errors`` — presigned-URL на CSV-отчёт ошибок (S3).

Все эндпоинты требуют роль ``MANAGER`` (RBAC, §11).
"""
import codecs
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_role
from app.db.session import get_db
from app.models.catalog import PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus, UserRole
from app.models.user import User
from app.repositories.catalog import fetch_price_list_versions, get_price_list_version
from app.schemas import MetaPage
from app.schemas.price_list import (
    ImportUploadOut,
    PriceListVersionPage,
    PriceListVersionRead,
)
from app.services import storage
from app.tasks.import_price_list import run_import

router = APIRouter(prefix="/prices", tags=["manager:prices"])

_MAX_BYTES = settings.import_max_file_mb * 1024 * 1024
_READ_CHUNK = 1024 * 1024
_HEADER_CAP = 1024 * 1024
_ALLOWED_CSV_CONTENT_TYPES = {
    "application/csv",
    "application/octet-stream",
    "application/vnd.ms-excel",
    "text/csv",
    "text/plain",
}


def _validate_upload_metadata(file: UploadFile) -> None:
    name = (file.filename or "").lower()
    if not any(name.endswith(ext) for ext in settings.import_allowed_ext_list):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Допустимы только файлы: {', '.join(settings.import_allowed_ext_list)}",
        )
    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in _ALLOWED_CSV_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Неподдерживаемый Content-Type для CSV",
        )


def _validate_header_line(header: str) -> None:
    separator = max((";", ",", "\t"), key=header.count)
    columns = {column.strip().casefold() for column in header.split(separator)}
    sku_aliases = {"sku", "артикул", "article"}
    name_aliases = {"name", "наименование", "название"}
    if not columns.intersection(sku_aliases) or not columns.intersection(name_aliases):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV должен содержать заголовок с колонками sku и name",
        )


async def _validate_csv_stream(file: UploadFile, *, max_bytes: int) -> None:
    """Потоковая валидация CSV (§7.1) без буферизации файла в памяти.

    Читаем чанками из spool-файла Starlette (крупные загрузки уже на диске).
    Порядок ошибок как у прежней in-memory версии: 413 → 415 → 400 → 422.
    """
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    header_text = ""
    header_done = False
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Файл превышает лимит {settings.import_max_file_mb} МБ",
            )
        if b"\x00" in chunk:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Файл не похож на текстовый CSV",
            )
        try:
            text = decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="CSV должен быть в кодировке UTF-8",
            ) from exc
        if not header_done and text:
            header_text += text
            if "\n" in header_text:
                header_done = True
            elif len(header_text) > _HEADER_CAP:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="CSV должен содержать заголовок с колонками sku и name",
                )
    try:
        decoder.decode(b"", final=True)  # обрубленный multi-byte хвост → не UTF-8
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="CSV должен быть в кодировке UTF-8",
        ) from exc
    if total == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
    lines = header_text.splitlines()
    _validate_header_line(lines[0] if lines else "")


@router.post(
    "/import",
    response_model=ImportUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_prices(
    file: UploadFile = File(..., description="CSV-прайс-лист (до 100 МБ)"),
    mode: ImportMode = Form(ImportMode.UPSERT, description="UPSERT | REPLACE | ARCHIVE_MISSING"),
    base_currency: str = Form("BYN", description="Валюта CSV (3 буквы)"),
    rate_to_byn: float = Form(1.0, description="Курс конвертации CSV→BYN (manual)"),
    db: AsyncSession = Depends(get_db),
    manager: User = Depends(require_role(UserRole.MANAGER)),
) -> ImportUploadOut:
    """Принять CSV, залить в MinIO (tmp-uploads) стримингом, запустить задачу.

    Конвертация цены в BYN делается в задаче по ``rate_to_byn`` (§17.2 Уровень 1).
    MVP: источник курса всегда MANUAL (``rate_source='MANUAL'``).
    """
    _validate_upload_metadata(file)
    await _validate_csv_stream(file, max_bytes=_MAX_BYTES)

    cur = (base_currency or "BYN").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="base_currency должна состоять ровно из 3 латинских букв",
        )
    rate = 1.0 if cur == "BYN" else float(rate_to_byn or 1.0)
    if rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="rate_to_byn должен быть > 0"
        )

    version = PriceListVersion(
        uploaded_by=manager.id,
        filename=file.filename or "upload.csv",
        import_mode=mode,
        status=PriceListVersionStatus.QUEUED,
        base_currency=cur,
        rate_to_byn=rate,
        rate_source="MANUAL",
    )
    db.add(version)
    await db.flush()  # получаем version.id без commit

    key = f"{version.id}/{version.filename}"
    try:
        await file.seek(0)
        # Стриминг spool-файла в MinIO (multipart, буфер — одна часть 8 МБ);
        # sync-клиент boto3 уводим в threadpool, чтобы не блокировать loop.
        await run_in_threadpool(
            storage.upload_fileobj,
            settings.s3_bucket_tmp, key, file.file,
            content_type="text/csv",
        )
    except storage.StorageError as exc:  # откатываем создание версии
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    await db.commit()
    run_import.delay(str(version.id))

    return ImportUploadOut(
        version_id=version.id,
        status=version.status,
        filename=version.filename,
        created_at=version.created_at,
    )


@router.get("/versions", response_model=PriceListVersionPage)
async def list_versions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> PriceListVersionPage:
    limit, offset = per_page, (page - 1) * per_page
    rows, total = await fetch_price_list_versions(db, limit=limit, offset=offset)
    return PriceListVersionPage(
        data=[PriceListVersionRead.model_validate(r) for r in rows],
        meta=MetaPage(page=page, per_page=per_page, total=total),
    )


@router.get("/versions/{version_id}", response_model=PriceListVersionRead)
async def get_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> PriceListVersionRead:
    version = await get_price_list_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версия не найдена")
    return PriceListVersionRead.model_validate(version)


@router.get("/versions/{version_id}/errors")
async def get_version_errors(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
) -> dict[str, str]:
    """Presigned-URL (5 мин) на CSV-отчёт ошибок импорта в S3 (error-logs)."""
    version = await get_price_list_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версия не найдена")
    if not version.error_log_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Отчёт об ошибках отсутствует"
        )
    try:
        url = storage.presigned_get(settings.s3_bucket_errors, version.error_log_key)
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return {"url": url}
