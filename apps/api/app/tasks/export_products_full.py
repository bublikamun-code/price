"""Полный экспорт продукции в CSV (Celery, менеджер): все характеристики
колонками + ссылки на фото отдельными колонками.

Контракт:
  Вход:  ``job_id`` — стейт в Redis ``export:job:{job_id}`` (QUEUED),
         ``user_id`` — владелец job'а (статус опрашивает только он).
  Шаги:
    1. статусы в Redis: RUNNING → DONE (s3_key) / FAILED (error);
    2. все товары (без deleted_at; ARCHIVED включены — выгрузка менеджера)
       + бренд/серия одним запросом, галереи фото — вторым (без N+1);
    3. характеристики (``products.attributes``, JSONB): объединение всех
       ключей → отсортированные колонки после базовых; скаляры — строками,
       вложенные list/dict — компактным JSON (ensure_ascii=False);
    4. фото: личное фото товара (первое по sort_order/created_at), иначе
       фото серии — как в карточке каталога; каждое фото — отдельная
       колонка «Фото N» со ссылкой ``{web_app_url}/api/v1/public/photo?key=…``
       (публичный whitelist-эндпоинт, без авторизации; presigned не подходит —
       TTL 5 мин против жизни CSV);
    5. CSV ``utf-8-sig`` + ``;`` → S3 ``csv-exports``,
       ключ ``export/products-full-{job_id}.csv``.

Идемпотентность/надёжность — по образцу ``tasks/export_catalog.py``:
слепой авто-ретрай отключён (``autoretry_for=()``), критическая ошибка
фиксирует FAILED и пишется в лог, не роняя worker.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import quote_plus

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.catalog import Brand, Product, ProductPhoto, Series
from app.services import storage
from app.tasks._common import create_worker_db, mark_redis_job_failed
from app.workers import celery_app

log = get_logger("app.tasks.export_products_full")

# Базовые колонки выгрузки (до динамических колонок характеристик и фото).
BASE_COLUMNS = [
    "Артикул",
    "Наименование",
    "Бренд",
    "Серия",
    "Статус",
    "Остаток",
    "Цена розничная",
    "Цена договорная",
]

_CONTENT_TYPE_CSV = "text/csv"

# Отдельный движок для Celery-задач (по образцу export_catalog): NullPool,
# т.к. каждая задача крутится в своём asyncio.run.
_worker_engine, _worker_session = create_worker_db()


@celery_app.task(bind=True, name="export_products_full", autoretry_for=())
def run_full_export(self, job_id: str, user_id: str) -> dict:
    """Запуск полного экспорта. Оборачивает async-пайплайн; ловит критические ошибки.

    Returns: ``{"job_id", "status", "rows"?, "error"?}``.
    """
    try:
        return asyncio.run(
            _run_full_export(uuid.UUID(job_id), uuid.UUID(user_id))
        )
    except Exception as exc:  # критическая ошибка → FAILED, без слепого ретрая
        log.exception("export_products_full.crashed", job_id=job_id, error=str(exc))
        asyncio.run(_mark_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}


# ----------------------------- async pipeline -----------------------------

async def _run_full_export(job_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    # Lazy-import: сервис стартует эту задачу (run_full_export) — избегаем
    # цикличности импортов на уровне модуля.
    from app.services.product_export import STATUS_DONE, STATUS_RUNNING, set_job_state

    await set_job_state(
        job_id, status=STATUS_RUNNING, started_at=datetime.now(UTC).isoformat()
    )

    async with _worker_session() as db:
        result = await db.execute(
            select(
                Product,
                Brand.name.label("brand_name"),
                Series.name.label("series_name"),
                Series.photo_key.label("series_photo_key"),
            )
            .outerjoin(Brand, Brand.id == Product.brand_id)
            .outerjoin(Series, Series.id == Product.series_id)
            .where(Product.deleted_at.is_(None))
            .order_by(Product.name.asc(), Product.id.asc())
        )
        rows = result.all()

        photos_by_product: dict[uuid.UUID, list[str]] = {}
        product_ids = [r[0].id for r in rows]
        if product_ids:
            photo_rows = await db.execute(
                select(ProductPhoto.product_id, ProductPhoto.photo_key)
                .where(ProductPhoto.product_id.in_(product_ids))
                .order_by(ProductPhoto.sort_order.asc(), ProductPhoto.created_at.asc())
            )
            for product_id, photo_key in photo_rows.all():
                photos_by_product.setdefault(product_id, []).append(photo_key)

        columns, records = build_table(rows, photos_by_product)

        body = _to_csv_bytes(columns, records)
        key = f"export/products-full-{job_id}.csv"
        storage.upload_fileobj(
            settings.s3_bucket_exports, key, io.BytesIO(body),
            content_type=_CONTENT_TYPE_CSV,
        )
        await set_job_state(job_id, status=STATUS_DONE, s3_key=key)
        log.info(
            "export_products_full.done",
            job_id=str(job_id), user_id=str(user_id),
            rows=len(records), columns=len(columns), key=key,
        )
        return {"job_id": str(job_id), "status": STATUS_DONE, "rows": len(records)}


# ----------------------------- сборка таблицы -----------------------------

def _photo_url(key: str) -> str:
    """S3-ключ фото → публичная ссылка (whitelist-эндпоинт /public/photo).

    ``web_app_url`` пуст (dev) — относительный путь: в CSV останется ключевой
    путь, который дописывается до хоста при развёртывании.
    """
    base = settings.web_app_url.rstrip("/")
    return f"{base}/api/v1/public/photo?key={quote_plus(key)}"


def _attr_value(value: object) -> str:
    """Значение характеристики → строка ячейки: скаляры as-is, вложенное — JSON."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def build_table(rows, photos_by_product: dict[uuid.UUID, list[str]]):
    """Строки каталога + галереи → (columns, records) для CSV.

    Колонки: базовые + объединение всех ключей характеристик (sorted) +
    «Фото 1»…«Фото N» (N — максимум фото у товара). Главное фото товара —
    первое личное, иначе фото серии (семантика карточки каталога).
    """
    attr_keys: set[str] = set()
    photo_lists: list[list[str]] = []
    for r in rows:
        product = r[0]
        attr_keys.update(str(k) for k in (product.attributes or {}))
        gallery = photos_by_product.get(product.id) or []
        photo_lists.append(gallery or ([r.series_photo_key] if r.series_photo_key else []))

    attr_columns = sorted(attr_keys)
    max_photos = max((len(p) for p in photo_lists), default=0)
    photo_columns = [f"Фото {i}" for i in range(1, max_photos + 1)]
    columns = BASE_COLUMNS + attr_columns + photo_columns

    records: list[list[str]] = []
    for r, photos in zip(rows, photo_lists):
        product = r[0]
        attributes = {str(k): v for k, v in (product.attributes or {}).items()}
        records.append(
            [
                product.sku,
                product.name,
                r.brand_name or "",
                r.series_name or "",
                product.stock_status.value,
                "" if product.stock_qty is None else str(product.stock_qty),
                f"{float(product.base_price):.2f}",
                "" if product.override_price is None
                else f"{float(product.override_price):.2f}",
            ]
            + [_attr_value(attributes.get(k)) for k in attr_columns]
            + [_photo_url(k) for k in photos]
            + [""] * (max_photos - len(photos))
        )
    return columns, records


# ----------------------------- файл -----------------------------

def _to_csv_bytes(columns: list[str], records: list[list[str]]) -> bytes:
    """CSV для Excel: UTF-8 c BOM, разделитель ``;`` (как у импорта, §7.1)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(columns)
    writer.writerows(records)
    return buf.getvalue().encode("utf-8-sig")


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    """Пометить job FAILED при критической ошибке (storage/неожиданное)."""
    await mark_redis_job_failed("app.services.product_export", job_id, message)
