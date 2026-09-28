"""Файловые активы (S3). См. ARCHITECTURE_PLAN.md §5, §10."""
import uuid

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import FileAssetType, FileVisibility, pg_enum


class FileAsset(Base, TimestampMixin, UUIDPrimaryKey):
    """Файл в S3: PDF-каталог бренда, спец-CSV, ZIP с фото и т.д. (§10)."""
    __tablename__ = "file_assets"

    type: Mapped[FileAssetType] = mapped_column(
        pg_enum(FileAssetType, "file_asset_type"), nullable=False
    )
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename_display: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[FileVisibility] = mapped_column(
        pg_enum(FileVisibility, "file_visibility"),
        nullable=False,
        default=FileVisibility.AUTHED,
    )


class MediaAsset(Base, TimestampMixin, UUIDPrimaryKey):
    """Реестр изображений каталога: стабильный id ↔ S3-ключ (§16 п.37).

    v2 отдаёт нативным клиентам `/api/v2/media/{mediaId}`, а не presigned-URL:
    presigned живёт 5 минут и не может быть ключом кэша ImageCache, поэтому
    нужен идентификатор, который не меняется. Он детерминирован —
    ``uuid5`` от S3-ключа, — и потому переживает перезапуск, повторный импорт и
    любой деплой, а сам S3-ключ остаётся на сервере и клиенту не отдаётся.

    Реестр нужен именно ради обратного перехода ``id → ключ``: ``uuid5``
    необратим, а эндпоинту media без ключа не выдать 307.
    """

    __tablename__ = "media_assets"

    s3_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    mime_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="image/webp"
    )
