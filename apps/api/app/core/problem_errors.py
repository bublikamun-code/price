"""Ошибки предметной области, не зависящие от транспортного слоя.

`V2ProblemError` — доменная ошибка, у которой уже есть стабильный код и HTTP-статус.
Раньше она жила в `app/api/v2/errors.py`, то есть в слое роутеров, и сервисы
импортировали её оттуда. Это вывернутое направление зависимостей: нижний слой
зависел от верхнего, а `app/api/v2/errors.py` при этом импортирует хендлеры
FastAPI — круговая связь на уровне пакетов.

Класс переехал сюда, потому что он не привязан к HTTP-транспорту, а нужен и
сервисам, и роутерам. В `app/api/v2/errors.py` он переэкспортируется, поэтому
все существующие `from app.api.v2.errors import V2ProblemError` продолжают работать.
"""

from __future__ import annotations

from app.schemas.v2.common import ProblemFieldError


class V2ProblemError(Exception):
    """Domain error that already has a stable v2 code and HTTP status."""

    def __init__(
        self,
        *,
        code: str,
        status: int,
        title: str,
        detail: str,
        errors: list[ProblemFieldError] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.errors = errors or []
        super().__init__(detail)