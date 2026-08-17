"""DTO файлового архива (file_assets). См. ARCHITECTURE_PLAN.md §6, §10, §16 п.18."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import FileAssetType, FileVisibility
from app.models.file import FileAsset
from app.schemas import MetaPage


class FileAssetOut(BaseModel):
    """Карточка файла архива (§16 п.18).

    ``filename`` — оригинальное имя (в модели ``filename_display``),
    ``brand_name`` — из outerjoin на brands, для отображения в списке.
    """

    id: uuid.UUID
    type: FileAssetType
    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    brand_id: uuid.UUID | None = None
    brand_name: str | None = None
    visibility: FileVisibility
    created_at: datetime

    @classmethod
    def from_asset(
        cls, asset: FileAsset, *, brand_name: str | None = None
    ) -> "FileAssetOut":
        """DTO из ORM-объекта (+ имя бренда из join'а, если есть)."""
        return cls(
            id=asset.id,
            type=asset.type,
            filename=asset.filename_display,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            brand_id=asset.brand_id,
            brand_name=brand_name,
            visibility=asset.visibility,
            created_at=asset.created_at,
        )


class FileAssetPage(BaseModel):
    """Страница списка файлов (envelope §6)."""

    data: list[FileAssetOut]
    meta: MetaPage


class FileDownloadOut(BaseModel):
    """Presigned-ссылка на файл (TTL 5 мин, §10)."""

    url: str
    expires_in: int = 300


class FileDownloadResponse(BaseModel):
    """Envelope §6 одиночного объекта: ``{"data": {"url", "expires_in"}}``."""

    data: FileDownloadOut
