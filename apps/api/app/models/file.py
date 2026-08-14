"""Файловые активы (S3). См. ARCHITECTURE_PLAN.md §5, §10."""
import uuid

from sqlalchemy import BigInteger, ForeignKey, String
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
