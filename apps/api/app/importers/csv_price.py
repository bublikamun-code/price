"""Конвертер CSV-прайс-листа → нормализованные строки товаров.

Чистый модуль (без БД, без I/O) → unit-тестируемый. См. ARCHITECTURE_PLAN.md §7.1.

Поток::
    header = ["Артикул", "Наименование", "Бренд", "Цена", "Скидка", "Наличие"]
    cols = resolve_columns(header)            # {canonical: actual} или SchemaError
    df = pl.read_csv(..., rename=...)         # колонки → canonical имена
    for row in df.iter_rows(named=True):      # row[canonical_field]
        res = normalize_row(row, row_num)
        # NormalizedRow | RowError

Конвертация валюты здесь НЕ делается — она требует ``rate_to_byn`` из
``PriceListVersion`` и применяется в задаче импорта (§17.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.enums import StockStatus

# Каноническое поле → допустимые заголовки CSV (регистронезависимо).
# Порядок алиасов — от каноничного к RU-вариантам.
COLUMN_ALIASES: dict[str, list[str]] = {
    "sku": ["sku", "article", "articul", "артикул", "артикул производителя"],
    "name": ["name", "title", "наименование", "название", "товар"],
    "brand": ["brand", "бренд", "производитель"],
    "series": ["series", "серия", "линейка"],
    "base_price": ["base_price", "price", "цена", "цена розница", "розница"],
    "discount_price": ["discount_price", "discount", "скидка", "цена скидка", "цена со скидкой"],
    "stock_status": ["stock_status", "stock", "наличие", "склад"],
    "series_photo": ["series_photo", "photo", "фото", "фото серии"],
}

REQUIRED_FIELDS = ("sku", "name")

# RU-алиасы наличия → StockStatus (§16 п.2: только В наличии / Под заказ).
STOCK_RU: dict[str, StockStatus] = {
    "в наличии": StockStatus.IN_STOCK,
    "есть в наличии": StockStatus.IN_STOCK,
    "под заказ": StockStatus.PREORDER,
    "ожидается": StockStatus.PREORDER,
    "нет в наличии": StockStatus.IN_STOCK,  # OUT_OF_STOCK убран из enum (§16 п.2) → дефолт
    "архив": StockStatus.ARCHIVED,
}

DEFAULT_BRAND = "Прочее"


class SchemaError(ValueError):
    """Файл целиком непригоден: нет обязательной колонки / пустой заголовок."""


@dataclass(frozen=True)
class NormalizedRow:
    row_num: int
    sku: str
    name: str
    brand: str
    series: str | None
    base_price: Decimal
    discount_price: Decimal | None
    stock_status: StockStatus
    series_photo: str | None


@dataclass(frozen=True)
class RowError:
    row_num: int
    column: str
    message: str


def detect_separator(header_line: str) -> str:
    """Определить разделитель по первой строке: ``;`` / ``,`` / ``\\t``.

    Дефолт — ``;`` (европейский стандарт, §7.1). Выбираем наиболее частый из
    кандидатов, чтобы корректно распознать файлы с запятой в дробях.
    """
    counts = {sep: header_line.count(sep) for sep in (";", ",", "\t")}
    best = max(counts, key=lambda s: counts[s])
    return best if counts[best] > 0 else ";"


def resolve_columns(header: list[str]) -> dict[str, str]:
    """Сопоставить канонические поля с реальными колонками CSV.

    Возвращает ``{canonical_field: actual_column_name}``. Неизвестные колонки
    игнорируются. Если хотя бы одно поле из :data:`REQUIRED_FIELDS` не найдено —
    :class:`SchemaError`.
    """
    # Индекс: нижний регистр, очищенный от лишних пробелов/BOM.
    norm: dict[str, str] = {}
    for col in header:
        key = _norm_header(col)
        if key and key not in norm:
            norm[key] = col

    resolved: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            actual = norm.get(alias)
            if actual is not None:
                resolved[field] = actual
                break

    missing = [f for f in REQUIRED_FIELDS if f not in resolved]
    if missing:
        raise SchemaError(f"Отсутствуют обязательные колонки: {', '.join(missing)}")
    return resolved


def normalize_row(row: dict[str, Any], row_num: int) -> NormalizedRow | RowError:
    """Нормализовать одну строку (ключи = канонические поля).

    Возвращает :class:`NormalizedRow` либо :class:`RowError` (без исключений):
    ошибку одной строки не валидно валить весь импорт (§7.2 шаг 3).
    """
    sku = _clean(row.get("sku"))
    if not sku:
        return RowError(row_num, "sku", "Артикул обязателен")

    name = _clean(row.get("name"))
    if not name:
        return RowError(row_num, "name", "Наименование обязательно")

    brand = _clean(row.get("brand")) or DEFAULT_BRAND
    series = _clean(row.get("series"))

    price = _to_decimal(row.get("base_price"))
    if price is None:
        return RowError(row_num, "base_price", "Цена обязательна и должна быть числом")
    if price <= 0:
        return RowError(row_num, "base_price", "Цена должна быть больше нуля")

    discount_raw = _clean(row.get("discount_price"))
    discount_price: Decimal | None = None
    if discount_raw:
        discount_price = _to_decimal(discount_raw)
        if discount_price is None or discount_price < 0:
            return RowError(
                row_num, "discount_price", "Скидка должна быть неотрицательным числом"
            )

    stock_status = _parse_stock(row.get("stock_status"))
    series_photo = _clean(row.get("series_photo"))

    return NormalizedRow(
        row_num=row_num,
        sku=sku,
        name=name,
        brand=brand,
        series=series,
        base_price=price,
        discount_price=discount_price,
        stock_status=stock_status,
        series_photo=series_photo,
    )


# ----------------------------- internals -----------------------------

_BOM = "\ufeff"


def _norm_header(col: str | None) -> str:
    if col is None:
        return ""
    return col.strip().lstrip(_BOM).lower().strip()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


_NUM_STRIP_RE = re.compile(r"[^\d,.\-]")


def _to_decimal(value: Any) -> Decimal | None:
    """Парсинг Decimal: accepts ``12.50`` / ``12,50`` / ``" 12.50 руб"``.

    Возвращает None, если значение пусто/нечисловое. Знак минус сохраняется.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = _clean(value)
    if not s:
        return None
    s = _NUM_STRIP_RE.sub("", s)
    if not s or s in {".", ",", "-", "-.", "-,"}:
        return None
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_stock(value: Any) -> StockStatus:
    if value is None:
        return StockStatus.IN_STOCK
    s = _clean(value)
    if not s:
        return StockStatus.IN_STOCK
    key = s.lower()
    if key in STOCK_RU:
        return STOCK_RU[key]
    # Имя enum как есть (IN_STOCK / PREORDER / ARCHIVED).
    try:
        return StockStatus[key.upper()]
    except KeyError:
        return StockStatus.IN_STOCK
