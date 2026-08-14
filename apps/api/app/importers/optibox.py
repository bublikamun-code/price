"""Импортёр каталога OptiBox Pro из выгрузки 1С-Битрикс.

Источник: ``OptiBox_Pro_Belarus.xlsx`` (лист «OptiBox Pro», экспорт 1С-Битрикс).
Колонки именованы кодами свойств Битрикса (``IP_PROP*``, ``IE_*``, ``CV_*``).

Функция :func:`row_to_product` чистая (без БД, без I/O) → unit-тестируемая.
На входе — ``dict``, сгруппированный по кодам колонок (заголовок листа).
На выходе — нормализованное представление товара для загрузки в каталог::

    {
        "sku": "379782",
        "name": "Корпус пластиковый OptiBox Pro 8-NNR-IP40",
        "brand": "KEAZ",
        "series": "OptiBox Pro",
        "base_price": 22.4,            # BYN, TEST (формула) — заменить реальным импортом
        "photo_url": "https://...",
        "attributes": { "modules": 8, "color": "Белый", "ip_rating": "IP40", ... },
    }

Загрузкой в БД занимается ``app/scripts/seed_catalog.py``.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# Коды колонок Битрикса → семантика (см. заголовок листа «OptiBox Pro»).
_COL = {
    "sku": "IP_PROP112",
    "name": "IE_NAME",
    "brand": "IP_PROP509",
    "series": "IP_PROP538",
    "modules_raw": "IP_PROP130",
    "color": "IP_PROP507",
    "mounting_type": "IP_PROP145",
    "ik_rating": "IP_PROP151",
    "material": "IP_PROP152",
    "window": "IP_PROP166",
    "temperature_range": "IP_PROP168",
    "din_rail": "IP_PROP177",
    "ip_rating": "IP_PROP184",
    "weight_raw": "IP_PROP132",
    "purpose": "IP_PROP133",
    "dim_a": "IP_PROP540",
    "dim_b": "IP_PROP553",
    "dim_c": "IP_PROP554",
    "unit": "CP_QUANTITY",
    "photo": "IE_PREVIEW_PICTURE",
}

#TEST: тестовая цена пока реальный прайс не подключён отдельным импортом (Этап 4).
# Базовая розничная цена в BYN, зависит от кол-ва модулей.
_PRICE_BASE = Decimal("8")
_PRICE_PER_MODULE = Decimal("1.8")


def _g(row: dict[str, Any], key: str) -> str | None:
    """Значение колонки по семантическому ключу; None/пусто → None."""
    val = row.get(_COL[key])
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _parse_modules(name: str | None, raw: str | None) -> int | None:
    """Кол-во модулей: только из имени («OptiBox Pro 8-NNR-...»).

    Колонка IP_PROP130 ненадёжна: для мультимедийных корпусов там лежит '1'
    (маркер серии), а не число DIN-модулей. У мультимод. корпусов в имени числа
    нет → возвращаем None (характеристика к ним не применима).
    """
    if name:
        m = re.search(r"OptiBox\s+Pro\s+(\d+)\s*-", name, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _dimensions(row: dict[str, Any]) -> list[int] | None:
    dims = [
        _to_int(_g(row, "dim_a")),
        _to_int(_g(row, "dim_b")),
        _to_int(_g(row, "dim_c")),
    ]
    return [d for d in dims if d] or None


def _test_base_price(modules: int | None) -> Decimal:
    """TEST-цена в BYN. ВНИМАНИЕ: временная, до импорта реального прайса (Этап 4).

    - DIN-корпуса: ``8 + 1.8 * modules`` (8→22.40, 12→29.60, 60→116.00).
    - Не-модульные (мультимедийные): плоская 30.00.
    """
    if modules is None:
        return Decimal("30.00")
    price = _PRICE_BASE + _PRICE_PER_MODULE * modules
    return price.quantize(Decimal("0.01"))


def row_to_product(row: dict[str, Any]) -> dict[str, Any]:
    """Нормализовать строку Bitrix → представление товара для каталога.

    ``row`` — dict с ключами-кодами колонок Битрикса (заголовок листа).
    Возвращает dict со ключами: sku, name, brand, series, base_price,
    photo_url, attributes.
    """
    name = _g(row, "name")
    modules = _parse_modules(name, _g(row, "modules_raw"))

    attributes: dict[str, Any] = {}
    if modules is not None:
        attributes["modules"] = modules
    for key in ("color", "mounting_type", "ik_rating", "material",
                "temperature_range", "din_rail", "ip_rating", "purpose", "unit"):
        val = _g(row, key)
        if val is not None:
            attributes[key] = val
    window = _g(row, "window")
    if window is not None:
        attributes["transparent_window"] = window
    dims = _dimensions(row)
    if dims:
        attributes["dimensions_mm"] = dims
    weight = _to_int(_g(row, "weight_raw"))
    if weight is not None:
        attributes["weight_g"] = weight

    photo_url = _g(row, "photo")
    if photo_url:
        attributes["photo_url"] = photo_url

    return {
        "sku": _g(row, "sku") or "",
        "name": name or "",
        "brand": _g(row, "brand") or "KEAZ",
        "series": _g(row, "series") or "OptiBox Pro",
        "base_price": float(_test_base_price(modules)),
        "photo_url": photo_url,
        "attributes": attributes,
    }
