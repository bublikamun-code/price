"""Сервисы жизненного цикла прайс-листа. См. ARCHITECTURE_PLAN.md §7.2, §16 п.14.

Use-case'ы:
  * ``start_import`` — принять CSV менеджера: создать ``PriceListVersion``
    (QUEUED), залить файл стримингом в S3 ``tmp-uploads/{version_id}/{filename}``
    и диспатчить Celery-задачу ``run_import``;
  * ``rollback_version`` — откатить DONE-версию к предыдущему состоянию
    (restore цен из истории + архивация новых товаров).

Исключение из правила «коммитит роутер» (§4): сервисы сами делают commit/
rollback — заливка в S3 требует отката версии при ``StorageError`` (иначе
останется версия без файла), а rollback меняет каталог и аудит версии
атомарно. ``StorageError``/``VersionNotRollbackable`` прокидываются наверх,
роутер мапит их в 502/409.
"""
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.catalog import PriceListVersion
from app.models.enums import ImportMode, PriceListVersionStatus
from app.repositories import catalog as catalog_repo
from app.services import storage
from app.services.cache import CATALOG_TAG, FILTERS_TAG, invalidate_tags
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


class VersionNotRollbackable(Exception):
    """Версия не удовлетворяет условиям отката (§16 п.14).

    ``reason`` — человекочитаемое объяснение, роутер отдаёт его как detail 409.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def rollback_version(
    db: AsyncSession,
    *,
    version_id: uuid.UUID,
    manager_id: uuid.UUID,
) -> tuple[PriceListVersion, int, int] | None:
    """Откатить DONE-версию прайса к предыдущему состоянию (§16 п.14).

    ``None`` — версия не найдена (роутер → 404). Гварды → ``VersionNotRollbackable``
    (роутер → 409): статус != DONE; есть более поздняя DONE-версия; откат
    уже выполнялся (``rolled_back_at``).

    Версия читается с ``FOR UPDATE`` (по образцу ``_lock_version`` задачи
    импорта) — исключает гонку двойного отката: конкурентный запрос заблокируется
    на чтении строки и увидит уже заполненный ``rolled_back_at``.

    Сервис владеет транзакцией (прецедент ``start_import``): массовое
    восстановление/архивация товаров и аудит ``rolled_back_at/by`` должны
    закоммититься атомарно. После commit — инвалидация кэша каталога/фильтров
    (как в ``tasks/import_price_list``; fail-open уже внутри cache-модуля).

    Возвращает ``(version, restored, archived)``.
    """
    version = await db.scalar(
        select(PriceListVersion)
        .where(PriceListVersion.id == version_id)
        .with_for_update()
    )
    if version is None:
        return None

    if version.status != PriceListVersionStatus.DONE:
        raise VersionNotRollbackable(
            "Откатить можно только версию в статусе DONE "
            f"(текущий: {version.status.value})"
        )
    later_done = await db.scalar(
        select(PriceListVersion.id)
        .where(
            PriceListVersion.status == PriceListVersionStatus.DONE,
            PriceListVersion.created_at > version.created_at,
        )
        .limit(1)
    )
    if later_done is not None:
        raise VersionNotRollbackable(
            "Существует более поздняя завершённая версия — сначала откатите её"
        )
    if version.rolled_back_at is not None:
        raise VersionNotRollbackable("Версия уже откачена")

    restored, archived = await catalog_repo.rollback_version(db, version_id)
    version.rolled_back_at = datetime.now(UTC)
    version.rolled_back_by = manager_id
    await db.commit()

    await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
    return version, restored, archived
