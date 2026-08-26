"""Экспорт каталога в CSV/XLSX/PDF (Celery). См. ARCHITECTURE_PLAN.md §16 п.16, п.25.

Контракт:
  Вход:  ``job_id`` — стейт в Redis ``export:job:{job_id}`` (QUEUED),
         ``user_id``/``filters_json``/``format``/``price_calc_mode`` — параметры
         выгрузки (персональные цены считаются под пользователя).
  Шаги:
    1. статусы в Redis: RUNNING → DONE (s3_key) / FAILED (error);
    2. ``fetch_catalog_all`` — весь каталог под фильтры (без пагинации);
    3. цены через ``PricingService.price_product`` (§8/§17) для каждой строки;
    4. файл (CSV ``utf-8-sig`` + ``;`` | XLSX/openpyxl | PDF/weasyprint,
       §16 п.25 — шаблон ``app/templates/pdf/catalog.j2``) → S3 ``csv-exports``,
       ключ ``export/{job_id}.{csv|xlsx|pdf}`` (presigned-ссылку отдаёт API).

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
from datetime import datetime

from openpyxl import Workbook

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import StockStatus
from app.models.user import User
from app.repositories import catalog as catalog_repo
from app.repositories.catalog import CatalogFilters
from app.services import storage
from app.services.pricing import PricingService
from app.tasks._common import create_worker_db, mark_redis_job_failed
from app.workers import celery_app

log = get_logger("app.tasks.export_catalog")

# Колонки выгрузки (§16 п.16): base_price — розница BYN, unit_price — цена
# клиента в валюте расчёта, currency — валюта расчёта (retail в BYN).
COLUMNS = ["sku", "name", "brand", "series", "stock_status",
           "base_price", "unit_price", "currency"]

_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

# Отдельный движок для Celery-задач (по образцу import_price_list): NullPool,
# т.к. каждая задача крутится в своём asyncio.run. Тесты подменяют
# ``_worker_session`` на свой sessionmaker (тестовый движок).
_worker_engine, _worker_session = create_worker_db()


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
        if format == "csv":
            body = _to_csv_bytes(records)
        elif format == "pdf":
            body = _to_pdf_bytes(records, user=user, price_calc_mode=price_calc_mode)
        else:
            body = _to_xlsx_bytes(records)
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


# Человекочитаемые подписи режима цен для шапки PDF (§8).
_PRICE_MODE_LABELS = {"fixed": "по договору (фикс. курс)",
                      "nbrb_current": "по текущему курсу НБ РБ"}


def _to_pdf_bytes(records: list[list], *, user, price_calc_mode: str) -> bytes:
    """PDF через weasyprint (§16 п.25): catalog.j2 → HTML → A4.

    weasyprint импортируется лениво: рендер выполняется только в Celery-воркере,
    API-процессу библиотека не нужна в рантайме (хотя и установлена).
    """
    from weasyprint import HTML

    from app.core.templates import render_pdf

    html = render_pdf(
        "catalog.j2",
        client_name=user.full_name,
        client_company=user.company,
        date=datetime.now().strftime("%d.%m.%Y"),
        price_mode=_PRICE_MODE_LABELS.get(price_calc_mode, price_calc_mode),
        rows=records,
    )
    return HTML(string=html).write_pdf()


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    """Пометить job FAILED при критической ошибке (storage/неожиданное)."""
    await mark_redis_job_failed("app.services.export", job_id, message)
