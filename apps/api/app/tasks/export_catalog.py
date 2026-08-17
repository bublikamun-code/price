"""Экспорт каталога в CSV/XLSX (Celery). См. ARCHITECTURE_PLAN.md §16 п.16.

Контракт:
  Вход:  ``job_id`` — стейт в Redis ``export:job:{job_id}`` (QUEUED),
         ``user_id``/``filters_json``/``format``/``price_calc_mode`` — параметры
         выгрузки (персональные цены считаются под пользователя).
  Шаги:
    1. статусы в Redis: RUNNING → DONE (s3_key) / FAILED (error);
    2. ``fetch_catalog_all`` — весь каталог под фильтры (без пагинации);
    3. цены через ``PricingService.price_product`` (§8/§17) для каждой строки;
    4. файл (CSV ``utf-8-sig`` + ``;`` либо XLSX/openpyxl) → S3 ``csv-exports``,
       ключ ``export/{job_id}.{csv|xlsx}`` (presigned-ссылку отдаёт API).

Идемпотентность/надёжность — по образцу ``tasks/import_price_list.py``:
слепой авто-ретрай отключён (``autoretry_for=()``), критическая ошибка
фиксирует FAILED и пишется в лог, не роняя worker.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid

from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import StockStatus
from app.models.user import User
from app.repositories import catalog as catalog_repo
from app.repositories.catalog import CatalogFilters
from app.services import storage
from app.services.pricing import PricingService
from app.workers import celery_app

log = get_logger("app.tasks.export_catalog")

# Колонки выгрузки (§16 п.16): base_price — розница BYN, unit_price — цена
# клиента в валюте расчёта, currency — валюта расчёта (retail в BYN).
COLUMNS = ["sku", "name", "brand", "series", "stock_status",
           "base_price", "unit_price", "currency"]

_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Отдельный движок для Celery-задач (по образцу import_price_list): NullPool,
# т.к. каждая задача крутится в своём asyncio.run. Тесты подменяют
# ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_worker_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_worker_engine, expire_on_commit=False
)


@celery_app.task(bind=True, name="export_catalog", autoretry_for=())
def run_export(
    self, job_id: str, user_id: str, filters_json: str, format: str,
    price_calc_mode: str,
) -> dict:
    """Запуск экспорта. Оборачивает async-пайплайн; ловит критические ошибки.

    Returns: ``{"job_id", "status", "rows"?, "error"?}``.
    """
    try:
        return asyncio.run(
            _run_export(uuid.UUID(job_id), uuid.UUID(user_id),
                        json.loads(filters_json), format, price_calc_mode)
        )
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception("export.crashed", job_id=job_id, error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _run_export(
    job_id: uuid.UUID, user_id: uuid.UUID, filters: dict, format: str,
    price_calc_mode: str,
) -> dict:
    # Lazy-import: services.export тянет эту задачу (run_export) наверх —
    # избегаем цикличности импортов на уровне модуля.
    from app.services.export import STATUS_DONE, STATUS_RUNNING, set_job_state

    await set_job_state(job_id, status=STATUS_RUNNING)

    async with _worker_session() as db:
        user = await db.get(User, user_id)
        if user is None:
            # Пользователь удалён между стартом job и выполнением.
            await set_job_state(job_id, status="FAILED", error="Пользователь не найден")
            return {"job_id": str(job_id), "status": "FAILED",
                    "error": "Пользователь не найден"}

        rows = await catalog_repo.fetch_catalog_all(
            db, user_id=user_id, filters=_filters_from_json(filters)
        )
        pricing = PricingService(db)
        records: list[list] = []
        for row in rows:
            product = row[0]
            prices = await pricing.price_product(product, user, price_calc_mode)
            records.append([
                product.sku,
                product.name,
                row.brand_name or "",
                row.series_name or "",
                product.stock_status.value,
                prices["base_price_byn"],
                prices["client_price"],
                prices["currency"],
            ])

        key = f"export/{job_id}.{format}"
        body = (
            _to_csv_bytes(records) if format == "csv" else _to_xlsx_bytes(records)
        )
        storage.upload_fileobj(
            settings.s3_bucket_exports, key, io.BytesIO(body),
            content_type=_CONTENT_TYPES[format],
        )
        await set_job_state(job_id, status=STATUS_DONE, s3_key=key)
        log.info("export.done", job_id=str(job_id), rows=len(records), key=key)
        return {"job_id": str(job_id), "status": STATUS_DONE, "rows": len(records)}


def _filters_from_json(filters: dict) -> CatalogFilters:
    """JSON из аргументов задачи → CatalogFilters (uuid/enum восстановлены)."""
    brand_ids = [uuid.UUID(b) for b in filters.get("brand_ids") or []]
    series_ids = [uuid.UUID(s) for s in filters.get("series_ids") or []]
    return CatalogFilters(
        q=filters.get("q"),
        brand_ids=brand_ids or None,
        series_ids=series_ids or None,
        stock=StockStatus(filters["stock"]) if filters.get("stock") else None,
    )


# ----------------------------- файлы -----------------------------

def _to_csv_bytes(records: list[list]) -> bytes:
    """CSV для Excel: UTF-8 c BOM, разделитель ``;`` (как у импорта, §7.1)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(COLUMNS)
    writer.writerows(records)
    return buf.getvalue().encode("utf-8-sig")


def _to_xlsx_bytes(records: list[list]) -> bytes:
    """XLSX через openpyxl в память (BytesIO) — без временных файлов."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Каталог"
    ws.append(COLUMNS)
    for record in records:
        ws.append(record)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    """Пометить job FAILED при критической ошибке (storage/неожиданное)."""
    from app.services.export import STATUS_FAILED, set_job_state

    await set_job_state(job_id, status=STATUS_FAILED, error=message[:500])
