"""Экспорт каталога (CSV/XLSX/PDF) и PDF-заявки: job-стейт в Redis + dispatch Celery.

Контракт:
  * ``start_export``     — создать job ``QUEUED`` (ключ ``export:job:{job_id}``,
    TTL 24 ч) и диспатчить Celery-задачу ``run_export``;
  * ``start_order_pdf``  — то же для PDF-заявки (§16 п.25, фича F):
    задача ``run_order_pdf``;
  * ``get_job``          — стейт job'а для его владельца (чужой/несуществующий
    → ``None``, роутер отдаёт 404);
  * ``set_job_state``    — частичное обновление стейта из задачи
    (``RUNNING`` → ``DONE``/``FAILED``).

Стейт живёт только в Redis (без строки в БД): выгрузка — эфемерный артефакт,
24-часового TTL достаточно; файлы в S3 ``csv-exports`` переживают ключ, но
presigned-ссылки живут 5 минут. Redis-ошибки не роняют API — fail-open
по образцу ``services/cache.py`` (safe_get/safe_set + log.warning).
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.catalog import CatalogFilters
from app.tasks.export_catalog import run_export

log = get_logger("app.services.export")

JOB_TTL_SECONDS = 24 * 60 * 60  # стейт job'а живёт сутки (§16 п.16)

# RUNNING дольше этого срока = воркер мёртв (hard time limit задачи — 30 мин,
# workers.py): отдаём клиенту FAILED вместо опроса до суточного TTL ключа.
STALE_RUNNING_AFTER_SECONDS = 30 * 60

# Статусы job'а (§6): QUEUED (создан) → RUNNING (воркер взял) → DONE/FAILED.
STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

_redis = Redis.from_url(settings.redis_url, decode_responses=True)


def _job_key(job_id) -> str:
    return f"export:job:{job_id}"


def _filters_to_json(filters: CatalogFilters) -> str:
    """Фильтры каталога → JSON для аргументов Celery-задачи (uuid → str)."""
    return json.dumps(
        {
            "q": filters.q,
            "brand_ids": [str(b) for b in (filters.brand_ids or [])],
            "series_ids": [str(s) for s in (filters.series_ids or [])],
            "stock": filters.stock.value if filters.stock else None,
        },
        ensure_ascii=False,
    )


async def start_export(
    *,
    user: User,
    filters: CatalogFilters,
    format: str,
    price_calc_mode: str,
) -> str:
    """Создать job (QUEUED) и запустить Celery-задачу. Возвращает ``job_id``.

    ``format`` уже провалидирован роутером (csv|xlsx).
    """
    job_id = uuid.uuid4()
    state = {
        "job_id": str(job_id),
        "user_id": str(user.id),
        "format": format,
        "status": STATUS_QUEUED,
        "error": None,
        "s3_key": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await safe_set_job(job_id, state)
    run_export.delay(str(job_id), str(user.id), _filters_to_json(filters),
                     format, price_calc_mode)
    return str(job_id)


async def start_order_pdf(*, user: User, order) -> str:
    """Создать job PDF-выгрузки заявки (§16 п.25, фича F) и диспатчить задачу.

    ``order`` уже проверена роутером (клиент-владелец или MANAGER); job
    привязывается к ``user`` — создателю (опрашивать статус может только он).
    """
    from app.tasks.export_order_pdf import run_order_pdf  # lazy: цикличность импортов

    job_id = uuid.uuid4()
    state = {
        "job_id": str(job_id),
        "user_id": str(user.id),
        "type": "order_pdf",
        "order_id": str(order.id),
        "format": "pdf",
        "status": STATUS_QUEUED,
        "error": None,
        "s3_key": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await safe_set_job(job_id, state)
    run_order_pdf.delay(str(job_id), str(order.id))
    return str(job_id)


async def get_job(user_id, job_id) -> dict[str, Any] | None:
    """Стейт job'а для владельца. ``None`` — нет ключа, Redis лежит или чужой.

    Стейт живёт только в Redis: если воркер умер, RUNNING никто не переведёт.
    Зависший RUNNING (``started_at``/``created_at`` старше дедлайна) на чтении
    перезаписывается FAILED («задача прервана»), чтобы клиент не поллил до TTL.
    """
    state = await safe_get_job(job_id)
    if state is None or state.get("user_id") != str(user_id):
        return None
    if state.get("status") == STATUS_RUNNING and _running_stale(state):
        state.update(status=STATUS_FAILED, error="Задача прервана: воркер не ответил")
        await safe_set_job(job_id, state)
        log.warning("export.job_stale_marked_failed", job_id=str(state.get("job_id")))
    return state


def _running_stale(state: dict[str, Any]) -> bool:
    """RUNNING начат раньше дедлайна? Отсчёт от ``started_at`` (fallback —
    ``created_at`` для ключей, записанных до появления heartbeat-поля)."""
    raw = state.get("started_at") or state.get("created_at")
    if not raw:
        return False
    try:
        started = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return datetime.now(UTC) - started > timedelta(seconds=STALE_RUNNING_AFTER_SECONDS)


async def set_job_state(job_id, **fields: Any) -> None:
    """Частично обновить стейт (status/s3_key/error), TTL продлевается.

    Job пишет только воркер-владелец задачи, поэтому get→set без CAS достаточно.
    Нет ключа (Redis чистился) — молча no-op: состояние восстановить неоткуда.
    """
    state = await safe_get_job(job_id)
    if state is None:
        return
    state.update(fields)
    await safe_set_job(job_id, state)


# ----- XLSX выгрузка заявки (синхронно, без job/Celery: заявка маленькая) -----

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Заголовки таблицы позиций (1С вставляет по колонкам — порядок фиксирован).
_ORDER_COLUMNS = ["Артикул", "Наименование", "Кол-во", "Цена", "Сумма"]


def build_order_xlsx(*, order, client, items) -> bytes:
    """XLSX заявки для переноса в 1С (openpyxl в память, без временных файлов).

    Лист «Заявка»: шапка (номер З-000XXX, дата, клиент, способ получения),
    таблица «Артикул | Наименование | Кол-во | Цена | Сумма» из
    ``product_snapshot`` + замороженных ``unit_price``/``quantity`` (§9),
    итоговая строка. Кол-во/цены/суммы — числами (не строками), чтобы 1С
    вставляла их как числа.
    """
    from app.services.email import DELIVERY_METHOD_RU, format_order_no  # lazy

    wb = Workbook()
    ws = wb.active
    ws.title = "Заявка"
    bold = Font(bold=True)

    # Шапка.
    ws.append(["Заявка", format_order_no(order.seq)])
    ws.append([
        "Дата",
        order.created_at.strftime("%d.%m.%Y") if order.created_at else "",
    ])
    ws.append(["Клиент", client.full_name or ""])
    if client.company:
        ws.append(["Компания", client.company])
    delivery = DELIVERY_METHOD_RU.get(order.delivery_method or "", "")
    if order.delivery_method == "delivery" and order.delivery_point:
        delivery = f"{delivery} ({order.delivery_point})"
    ws.append(["Способ получения", delivery])
    ws.append([])  # отступ перед таблицей

    # Таблица позиций.
    header_row = ws.max_row + 1
    ws.append(_ORDER_COLUMNS)
    total = 0.0
    for i in items:
        snap = i.product_snapshot or {}
        qty = int(i.quantity)
        price = float(i.unit_price)
        amount = round(qty * price, 2)
        total += amount
        ws.append([snap.get("sku", ""), snap.get("name", ""), qty, price, amount])

    # Итоговая строка.
    totals_row = ws.max_row + 1
    ws.append(["", "Итого", "", "", round(float(order.total_amount), 2)])

    for row in (header_row, totals_row):
        for cell in ws[row]:
            cell.font = bold

    # Авто-подбор ширин по длине значений колонок.
    for col in range(1, len(_ORDER_COLUMNS) + 2):
        width = max(
            (
                len(str(cell.value))
                for cells in ws.iter_rows(min_col=col, max_col=col)
                for cell in cells
                if cell.value is not None
            ),
            default=10,
        )
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = min(
            max(width + 2, 10), 60
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def order_xlsx_headers(*, seq: int | None, order_id: uuid.UUID) -> dict[str, str]:
    """Content-Type + Content-Disposition для скачивания xlsx заявки."""
    no = f"-{seq:03d}" if seq else ""
    filename = f"order{no}-{str(order_id)[:8]}.xlsx"
    return {
        "Content-Type": _XLSX_MEDIA_TYPE,
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


# ----- fail-open обёртки (§4: Redis не должен валить экспорт/каталог) -----

async def safe_get_job(job_id) -> dict[str, Any] | None:
    """Redis недоступен → «job не найден» (роутер отдаст 404)."""
    try:
        raw = await _redis.get(_job_key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        log.warning("export.job_get_failed", job_id=str(job_id), error=str(exc))
        return None


async def safe_set_job(job_id, state: dict[str, Any]) -> None:
    """Redis недоступен → стейт не сохраняется, но API продолжает работать."""
    try:
        await _redis.set(
            _job_key(job_id), json.dumps(state, ensure_ascii=False), ex=JOB_TTL_SECONDS
        )
    except Exception as exc:
        log.warning("export.job_set_failed", job_id=str(job_id), error=str(exc))
