"""Сервис запуска импорта прайс-листа. См. ARCHITECTURE_PLAN.md §7.2.

Use-case «принять CSV менеджера»: создать ``PriceListVersion`` (QUEUED),
залить файл стримингом в S3 ``tmp-uploads/{version_id}/{filename}`` и
диспатчить Celery-задачу ``run_import``.

Исключение из правила «коммитит роутер» (§4): сервис сам делает commit/rollback —
заливка в S3 требует отката версии при ``StorageError``, иначе останется версия
без файла. ``StorageError`` прокидывается наверх, роутер мапит её в 502.
"""
import uuid

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catalog import PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus
from app.services import storage
from app.tasks.import_price_list import run_import


async def start_import(
    db: AsyncSession,
    *,
    manager_id: uuid.UUID,
    upload: UploadFile,
    mode: ImportMode,
    base_currency: str,
    rate_to_byn: float,
) -> PriceListVersion:
    """Создать версию прайса (QUEUED), залить CSV в MinIO, запустить задачу.

    Стриминг spool-файла в MinIO (§7.2, streaming upload): boto3 multipart
    читает ``fileobj`` частями по 8 МБ; sync-клиент уходим в threadpool,
    чтобы не блокировать event loop. ``mode/base_currency/rate_to_byn``
    уже провалидированы роутером (HTTP-концерны остаются там).
    """
    version = PriceListVersion(
        uploaded_by=manager_id,
        filename=upload.filename or "upload.csv",
        import_mode=mode,
        status=PriceListVersionStatus.QUEUED,
        base_currency=base_currency,
        rate_to_byn=rate_to_byn,
        rate_source="MANUAL",
    )
    db.add(version)
    await db.flush()  # получаем version.id без commit

    key = f"{version.id}/{version.filename}"
    try:
        await upload.seek(0)
        await run_in_threadpool(
            storage.upload_fileobj,
            settings.s3_bucket_tmp, key, upload.file,
            content_type="text/csv",
        )
    except storage.StorageError:
        # Файл не залился — версию откатываем, ошибку отдаём роутеру (→ 502).
        await db.rollback()
        raise

    await db.commit()
    run_import.delay(str(version.id))
    return version
