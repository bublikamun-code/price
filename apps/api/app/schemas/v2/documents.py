"""API v2 DTO документов на товар (§16 п.38, docs/API_V2_CONTRACT.md §8).

Сертификаты и datasheets, привязанные к товару или его серии. Внутренний
S3-ключ наружу не уходит — скачивание байтами через
``GET /api/v2/catalog/products/{productId}/documents/{documentId}/download``
(не presigned — правило §9 «Media»).

``is_expired`` вычисляется сервером (``valid_until < today``): просроченный
документ **помечается, а не скрывается** — клиенту виднее, истёк ли сертификат.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.models.file import FileAsset
from app.schemas.v2.common import V2Model

DocumentType = Literal["CERTIFICATE", "DATASHEET"]
DocumentScope = Literal["product", "series"]


class ProductDocument(V2Model):
    """Документ карточки товара (свой или унаследованный из серии)."""

    id: uuid.UUID
    type: DocumentType
    file_name: str = Field(min_length=1, max_length=512)
    scope: DocumentScope
    valid_until: date | None = None
    is_expired: bool = False

    @classmethod
    def from_asset(cls, asset: FileAsset, *, scope: DocumentScope) -> "ProductDocument":
        return cls(
            id=asset.id,
            type=asset.type.value if hasattr(asset.type, "value") else str(asset.type),
            file_name=asset.filename_display,
            scope=scope,
            valid_until=asset.valid_until,
            is_expired=(
                asset.valid_until is not None and asset.valid_until < date.today()
            ),
        )


__all__ = ["DocumentScope", "DocumentType", "ProductDocument"]
