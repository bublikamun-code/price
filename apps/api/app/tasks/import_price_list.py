"""Импорт прайс-листа из CSV (Celery).

См. ARCHITECTURE_PLAN.md §7 (пайплайн), §16 п.3 (override_price — сохранение),
§17.2 (курс прайса, MANUAL на MVP).

Контракт:
  Вход:  ``version_id`` — ``PriceListVersion`` в статусе ``QUEUED``, файл уже в
         S3 ``tmp-uploads/{version_id}/{filename}``.
  Шаги:
    1. скачать CSV из S3;
    2. ``polars.read_csv`` + сопоставление колонок (§7.1);
    3. нормализация всех строк (без БД) → точная нумерация для отчёта ошибок;
    4. батчами по ``BATCH_SIZE``: upsert товаров + запись PriceHistory, конвертация
       цены в BYN по ``rate_to_byn``; при DB-ошибке батча строки идут в отчёт;
    5. ``ARCHIVE_MISSING``/``REPLACE`` → soft-delete отсутствующих;
    6. ``status=DONE``, счётчики ``rows_ok/rows_error``;
    7. ошибки → CSV-отчёт в S3 ``error-logs/`` (ключ в ``error_log_key``).

Идемпотентность: задача стартует только при ``status=QUEUED`` (иначе no-op);
слепой авто-ретрай отключён (``autoretry_for=()``) — критическая ошибка фиксирует
``status=FAILED`` и пишется в лог, без риска двойного прогона.
"""
from __future__ import annotations

import asyncio
import csv
import io
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import polars as pl
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.importers.csv_price import (
    NormalizedRow,
    RowError,
    SchemaError,
    detect_separator,
    normalize_row,
    resolve_columns,
)
from app.models.catalog import Brand, PriceListVersion, Series
from app.models.enums import ImportMode, PriceListVersionStatus
from app.repositories.catalog import (
    add_price_history,
    archive_missing,
    get_or_create_brand,
    get_or_create_series,
    upsert_product,
)
from app.services import storage
from app.services.cache import CATALOG_TAG, FILTERS_TAG, invalidate_tags
from app.tasks._common import create_worker_db
from app.workers import celery_app

log = get_logger("app.tasks.import_price_list")

BATCH_SIZE = 2000
TWO_PLACES = Decimal("0.01")

# Отдельный движок для Celery-задач: NullPool (зачем — см. tasks/_common.py).
# Тесты подменяют ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine, _worker_session = create_worker_db()


@celery_app.task(bind=True, name="import_price_list", autoretry_for=())
def run_import(self, version_id: str) -> dict:
    """Запуск импорта. Оборачивает async-пайплайн; ловит критические ошибки.

    Returns: ``{"version_id", "rows_ok", "rows_error", "rows_total", "status"}``.
    """
    try:
        return asyncio.run(_run_import(uuid.UUID(version_id)))
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception("import.crashed", version_id=str(version_id), error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(version_id), str(exc)))
        return {"version_id": str(version_id), "status": "FAILED", "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _run_import(version_id: uuid.UUID) -> dict:
    async with _worker_session() as db:
        version = await _lock_version(db, version_id)
        if version is None:
            # Уже обработана (не QUEUED) — идемпотентный no-op.
            log.info("import.skipped_not_queued", version_id=str(version_id))
            return {"version_id": str(version_id), "status": "skipped"}

        try:
            rows_ok, rows_error, rows_total = await _process(db, version)
            # Триггер уведомлений об изменении цен (§20.4, §7.2 шаг 8).
            # Lazy-import: notifications тянет много зависимостей, избегаем
            # цикличности на верхнем уровне модуля.
            from app.tasks.notifications import dispatch_price_changed

            try:
                dispatch_price_changed.delay(str(version_id))
            except Exception as exc:
                # Импорт уже зафиксирован как DONE. Не откатываем его из-за
                # недоступного брокера, но оставляем явный сигнал для алерта и
                # ручной повторной постановки уведомления.
                log.exception(
                    "import.price_notification_dispatch_failed",
                    version_id=str(version_id),
                    error=str(exc),
                )
        except SchemaError as exc:
            # Файл целиком непригоден: версия DONE с одной ошибкой схемы.
            await _finalize(db, version, ok=0, err=1, total=0,
                            errors=[RowError(1, "_schema", str(exc))])
            log.warning("import.schema_error", version_id=str(version_id), error=str(exc))
            return {"version_id": str(version_id), "status": version.status,
                    "rows_ok": 0, "rows_error": 1, "rows_total": 0}
        # storage.StorageError и прочее — пробрасываем → FAILED в run_import.

        return {
            "version_id": str(version_id),
            "status": version.status,
            "rows_ok": rows_ok,
            "rows_error": rows_error,
            "rows_total": rows_total,
        }


async def _process(db, version: PriceListVersion) -> tuple[int, int, int]:
    """Скачать → распарсить → нормализовать → upsert батчами → архивация → финал."""
    s3_key = f"{version.id}/{version.filename}"
    try:
        data = storage.get_bytes(settings.s3_bucket_tmp, s3_key)
    finally:
        # CSV уже прочитан в память; временный объект не нужен даже при ошибке
        # разбора и не должен бессрочно накапливаться в tmp-бакете.
        try:
            storage.delete_object(settings.s3_bucket_tmp, s3_key)
        except storage.StorageError as exc:
            log.warning(
                "import.tmp_object_delete_failed",
                version_id=str(version.id),
                s3_key=s3_key,
                error=str(exc),
            )
    data = _strip_bom(data)
    header_line = data.split(b"\n", 1)[0].decode("utf-8", "replace")
    separator = detect_separator(header_line)

    df = pl.read_csv(
        io.BytesIO(data),
        separator=separator,
        has_header=True,
        infer_schema_length=0,        # все колонки как строки → единая нормализация
        truncate_ragged_lines=True,
    )
    col_map = resolve_columns(df.columns)            # {canonical: actual}
    df = df.rename({actual: canon for canon, actual in col_map.items()})
    rows_total = df.height

    # --- проход 1: нормализация всех строк (чистая, без БД) ---
    normalized: list[tuple[int, NormalizedRow]] = []
    errors: list[RowError] = []
    for row_num, raw in enumerate(df.iter_rows(named=True), start=2):  # 1 = заголовок
        res = normalize_row(raw, row_num)
        if isinstance(res, RowError):
            errors.append(res)
        else:
            normalized.append((row_num, res))

    # --- проход 2: upsert батчами в БД ---
    rate = Decimal(str(version.rate_to_byn or 1))
    seen_skus: set[str] = set()
    rows_ok = 0

    # Кэши brand/series по имени (сбрасываются при rollback батча).
    brand_cache: dict[str, Brand] = {}
    series_cache: dict[tuple[str, str], Series] = {}

    async def _brand(name: str) -> uuid.UUID:
        key = name.lower().strip()
        if key not in brand_cache:
            brand_cache[key] = await get_or_create_brand(db, name=name)
        return brand_cache[key].id

    async def _series(name: str, brand_id: uuid.UUID, photo: str | None = None) -> uuid.UUID:
        key = (name.lower().strip(), str(brand_id))
        if key not in series_cache:
            series_cache[key] = await get_or_create_series(
                db, name=name, brand_id=brand_id, photo_key=photo
            )
        return series_cache[key].id

    for chunk in _chunks(normalized, BATCH_SIZE):
        try:
            for _row_num, nr in chunk:
                base_byn = (nr.base_price * rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                brand_id = await _brand(nr.brand)
                # series_photo (§7, §16 п.17) — «сырое» имя файла фото серии:
                # сохранится в series.photo_key до появления webp из photo-ZIP.
                series_id = (
                    await _series(nr.series, brand_id, nr.series_photo)
                    if nr.series else None
                )
                has_discount = nr.discount_price is not None
                # discount_price тоже в валюте CSV → конвертируем в BYN (§17.2),
                # override_price хранится в BYN наравне с base_price.
                override_byn = (
                    (nr.discount_price * rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                    if has_discount else None
                )
                product, _created = await upsert_product(
                    db,
                    sku=nr.sku,
                    name=nr.name,
                    brand_id=brand_id,
                    series_id=series_id,
                    base_price=base_byn,
                    stock_status=nr.stock_status,
                    price_list_version_id=version.id,
                    override_price=override_byn,
                    update_override=has_discount,
                    stock_qty=nr.stock_qty,
                    # Колонки остатка нет в CSV → не трогаем ранее заведённый остаток.
                    update_stock_qty="stock_qty" in col_map,
                )
                await add_price_history(
                    db,
                    product_id=product.id,
                    base_price=base_byn,
                    override_price=(
                        override_byn if has_discount else product.override_price
                    ),
                    price_list_version_id=version.id,
                )
                seen_skus.add(nr.sku)
            await db.commit()
            rows_ok += len(chunk)
        except Exception as exc:
            await db.rollback()
            brand_cache.clear()
            series_cache.clear()
            log.warning("import.batch_failed", version_id=str(version.id), error=str(exc))
            for row_num, _nr in chunk:
                errors.append(RowError(row_num, "_db", f"ошибка записи: {exc}"))

    # --- архивация отсутствующих (ARCHIVE_MISSING / REPLACE) ---
    if version.import_mode in (ImportMode.ARCHIVE_MISSING, ImportMode.REPLACE) and seen_skus:
        archived = await archive_missing(db, keep_skus=seen_skus)
        await db.commit()
        log.info("import.archived_missing", version_id=str(version.id), count=archived)

    await _finalize(db, version, ok=rows_ok, err=len(errors),
                    total=rows_total, errors=errors)
    await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
    return rows_ok, len(errors), rows_total


# ----------------------------- helpers -----------------------------

async def _lock_version(db, version_id: uuid.UUID) -> PriceListVersion | None:
    """Вернуть версию и перевести в PROCESSING. None — если не QUEUED (no-op).

    ``FOR UPDATE`` (по образцу ``rollback_version``): при ``acks_late``+
    ``reject_on_worker_lost`` задачу может взять второй воркер до того, как
    первый закоммитит PROCESSING — без блокировки строки оба прошли бы проверку
    QUEUED и импортировали параллельно.
    """
    version = await db.scalar(
        select(PriceListVersion)
        .where(PriceListVersion.id == version_id)
        .with_for_update()
    )
    if version is None or version.status != PriceListVersionStatus.QUEUED:
        return None
    version.status = PriceListVersionStatus.PROCESSING
    version.started_at = datetime.utcnow()
    await db.commit()
    return version


async def _finalize(db, version, *, ok: int, err: int, total: int,
                    errors: Sequence[RowError]) -> None:
    version.rows_total = total
    version.rows_ok = ok
    version.rows_error = err
    version.status = PriceListVersionStatus.DONE
    version.finished_at = datetime.utcnow()
    if errors:
        key = f"{version.id}.csv"
        storage.put_bytes(settings.s3_bucket_errors, key, _errors_to_csv(errors),
                          content_type="text/csv")
        version.error_log_key = key
    await db.commit()


async def _mark_failed(version_id: uuid.UUID, message: str) -> None:
    """Пометить версию FAILED при критической ошибке (storage/неожиданное)."""
    async with _worker_session() as db:
        version = await db.scalar(
            select(PriceListVersion).where(PriceListVersion.id == version_id)
        )
        if version is None:
            return
        if version.status not in (PriceListVersionStatus.QUEUED,
                                  PriceListVersionStatus.PROCESSING):
            return
        version.status = PriceListVersionStatus.FAILED
        version.finished_at = datetime.utcnow()
        log.warning("import.marked_failed", version_id=str(version_id), message=message)
        await db.commit()


# ----------------------------- beat-reconciler -----------------------------

# Дедлайн «зависшего» импорта. Soft time limit задачи — 25 минут (workers.py),
# поэтому PROCESSING дольше STUCK_IMPORT_HOURS означает, что воркер умер:
# при acks_late + reject_on_worker_lost задача доставляется повторно, но уходит
# в «skipped» (см. _run_import) и _mark_failed не вызывается — без reconciler'а
# версия висела бы в PROCESSING вечно.
STUCK_IMPORT_HOURS = 6


@celery_app.task(
    bind=True,
    name="app.tasks.import_price_list.reconcile_stuck_imports",
    autoretry_for=(),
)
def reconcile_stuck_imports(self) -> dict:
    """Beat каждые 15 мин: PROCESSING-версии старше 6 ч → FAILED (§7.2)."""
    try:
        return asyncio.run(_reconcile_stuck())
    except Exception as exc:  # непредвиденное — без слепого ретрая
        log.exception("import.reconcile.crashed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def _reconcile_stuck() -> dict:
    """Перевести зависшие PROCESSING-версии в FAILED через ``_mark_failed``."""
    cutoff = datetime.now(UTC) - timedelta(hours=STUCK_IMPORT_HOURS)
    async with _worker_session() as db:
        stale_ids = (
            await db.scalars(
                select(PriceListVersion.id).where(
                    PriceListVersion.status == PriceListVersionStatus.PROCESSING,
                    PriceListVersion.started_at < cutoff,
                )
            )
        ).all()
    for version_id in stale_ids:
        await _mark_failed(version_id, "импорт прерван: воркер не завершил задачу")
    if stale_ids:
        log.warning(
            "import.reconciled_stale",
            count=len(stale_ids),
            older_than_hours=STUCK_IMPORT_HOURS,
        )
    return {"status": "ok", "reconciled": len(stale_ids)}


def _errors_to_csv(errors: Sequence[RowError]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row", "column", "message"])
    for e in errors:
        writer.writerow([e.row_num, e.column, e.message])
    return buf.getvalue().encode("utf-8")


def _strip_bom(data: bytes) -> bytes:
    return data.decode("utf-8-sig").encode("utf-8")


def _chunks(seq: Sequence, size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])
