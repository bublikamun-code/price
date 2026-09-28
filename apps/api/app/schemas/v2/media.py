"""API v2 media DTO (§16 п.37, docs/NATIVE_API_CONTRACT.md §6.1).

Нативные клиенты кэшируют картинки по `id` и грузят по `url`, который ведёт на
стабильный v2-эндпоинт. Presigned-URL наружу не отдаётся: он протухает за 5
минут и в качестве ключа кэша каждый раз создавал бы новую запись.
"""
from __future__ import annotations

from pydantic import Field

from app.schemas.v2.common import V2Model


class MediaResource(V2Model):
    """Одно изображение каталога.

    `id` стабилен и пригоден как ключ кэша, `url` ведёт на стабильный v2-путь.
    Геометрия и MIME-тип — по конвенции загрузчика фото (см. services/media.py).
    """

    id: str
    url: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    mime_type: str


__all__ = ["MediaResource"]
