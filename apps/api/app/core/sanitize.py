"""Санитизация недоверенного ввода на выходе: имена файлов, заголовки, CSV/XLSX.

См. ARCHITECTURE_PLAN.md §11 («не доверять имени файла»).

Три независимые угрозы, три функции:

1. `safe_filename` / `content_disposition` — имя файла из multipart попадает
   в заголовок `Content-Disposition`. Управляющие символы (`\\r`, `\\n`) —
   ASCII, поэтому `encode("ascii", "ignore")` их НЕ вырезает, а uvicorn пишет
   заголовки байт-в-байт. Итог — response splitting, подмена Content-Type и
   reflected XSS в origin API. Лечится здесь и при записи в БД.

2. `spreadsheet_cell` — Excel/LibreOffice вычисляют ячейку, начинающуюся с
   `=`, `+`, `-`, `@`, даже если `csv.writer` её процитировал. В XLSX
   openpyxl дополнительно превращает такое значение в живую формулу
   (`data_type='f'`). Клиентский `delivery_point` доходит до выгрузки «для 1С».
"""
from __future__ import annotations

import re
from urllib.parse import quote

# Управляющие символы C0 + DEL. Отдельно вырезаем и кавычки/обратный слэш:
# они ломают синтаксис значения заголовка.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_HEADER_QUOTES = re.compile(r'["\\]')

# Строгий белый список для ASCII-фолбэка в Content-Disposition: буквы, цифры,
# точка, дефис, подчёркивание. Ничего, что может быть разделителем заголовка.
_ASCII_SAFE = re.compile(r"[^A-Za-z0-9._-]")

# Оговорка про `-`: в выгрузках прайса встречаются отрицательные числа и
# проценты («-12.50», «-0.5%»), поэтому `-` нейтрализуется только если дальше
# не число. Остальные символы опасны всегда.
_LEADING_MINUS_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?\s*%?$")

_MAX_FILENAME_LEN = 200


def safe_filename(name: str | None, *, default: str = "file") -> str:
    """Приводит недоверенное имя файла к безопасному виду.

    Отрезает путь (включая Windows-разделители и `..`), вырезает управляющие
    символы, ограничивает длину. Не гарантирует наличие расширения — это задача
    валидатора загрузки. Возвращает `default`, если после очистки ничего не
    осталось или осталось только имя точки.
    """
    if not name:
        return default
    # Отрезаем всё до последнего разделителя — `../../etc/passwd` → `passwd`.
    base = re.split(r"[\\/]", str(name))[-1]
    base = _CONTROL_CHARS.sub("_", base).strip().strip(".")
    if not base:
        return default
    if len(base) > _MAX_FILENAME_LEN:
        stem, dot, ext = base.rpartition(".")
        if dot and 0 < len(ext) <= 12:
            keep = _MAX_FILENAME_LEN - len(ext) - 1
            base = f"{stem[:keep]}.{ext}"
        else:
            base = base[:_MAX_FILENAME_LEN]
    return base


def content_disposition(filename: str | None, *, default: str = "document.pdf") -> str:
    """Значение заголовка Content-Disposition, безопасное для ответа.

    ASCII-фолбэк строится по строгому белому списку, поэтому управляющие
    символы и кавычки физически не могут попасть в заголовок. Полное имя
    (в т.ч. кириллица) передаётся через RFC 5987 `filename*`.
    """
    safe = safe_filename(filename, default=default)
    ascii_fallback = _ASCII_SAFE.sub("_", safe.encode("ascii", "ignore").decode())
    ascii_fallback = _HEADER_QUOTES.sub("", ascii_fallback).strip("._ ") or "download"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe)}"


def spreadsheet_cell(value: object) -> object:
    """Нейтрализует значение перед записью в CSV/XLSX (CSV injection).

    Excel/LibreOffice вычисляют ячейку, начинающуюся с `=`, `+`, `-`, `@`,
    TAB или CR, даже процитированную `csv.writer`. Апостроф-префикс делает
    значение текстом и убирает вычисление.

    Оговорка про `-`: в выгрузках прайса встречаются отрицательные числа
    (скидки), поэтому `-` нейтрализуется только если дальше не число —
    иначе экспорт превратил бы `-12.50` в текст и сломал бы вычисления
    в самом Excel. Остальные символы опасны всегда.
    """
    if not isinstance(value, str) or not value:
        return value
    # Проверяем и исходную строку, и после lstrip: `"\t=cmd"` опасен так же,
    # как `"=cmd"`, и Excel смотрит на первый символ до отсечения пробелов.
    for candidate in (value, value.lstrip()):
        head = candidate[:1]
        if head in ("=", "+", "@", "\t", "\r"):
            return "'" + value
        if head == "-":
            if not _LEADING_MINUS_NUMBER.match(candidate.strip()):
                return "'" + value
    return value