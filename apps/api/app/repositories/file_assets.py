"""Репозиторий файлового архива (file_assets). См. ARCHITECTURE_PLAN.md §6
(files), §10 (S3), §16 п.18 (контракт).

Только запросы к БД; валидация загрузки и S3 — в ``services/file_assets``.
``brand_name`` тянется через outerjoin на brands (для отображения).
Как и соседние репозитории — только ``flush``, коммитит роутер (§4).
"""
import uuid
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand
from app.models.enums import FileAssetType, FileVisibility
from app.models.file import FileAsset


@dataclass
class FileAssetFilters:
    """Фильтры списка архива (§16 п.18).

    ``visibilities=None`` — без ограничения (MANAGER); для CLIENT роутер
    передаёт ``(PUBLIC, AUTHED)``.
    """

    type: FileAssetType | None = None
    brand_id: uuid.UUID | None = None
    visibilities: Sequence[FileVisibility] | None = None

    def has_any(self) -> bool:
        return any([self.type, self.brand_id, self.visibilities])


def _apply_filters(stmt, filters: FileAssetFilters):
    """Общая WHERE-логика списка/счётчика архива."""
    if filters.type:
        stmt = stmt.where(FileAsset.type == filters.type)
    if filters.brand_id:
        stmt = stmt.where(FileAsset.brand_id == filters.brand_id)
    if filters.visibilities:
        stmt = stmt.where(FileAsset.visibility.in_(filters.visibilities))
    return stmt


def _rows_stmt():
    """Базовый select: файл + имя бренда (outerjoin, brand может не быть)."""
    return select(FileAsset, Brand.name.label("brand_name")).outerjoin(
        Brand, Brand.id == FileAsset.brand_id
    )


async def fetch_file_assets(
    db: AsyncSession, *, filters: FileAssetFilters, limit: int, offset: int
) -> tuple[list, int]:
    """Список файлов (новые первыми) + общее кол-во под фильтры.

    Возвращает ``(rows, total)``: ``row[0]`` — ``FileAsset``,
    ``row[1]`` — ``brand_name | None``.
    """
    total = await db.scalar(_apply_filters(select(func.count(FileAsset.id)), filters))
    stmt = (
        _apply_filters(_rows_stmt(), filters)
        .order_by(FileAsset.created_at.desc(), FileAsset.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    return rows, int(total or 0)


async def get_file_asset(db: AsyncSession, file_id: uuid.UUID):
    """Файл по id + ``brand_name`` (Row), либо ``None``."""
    stmt = _rows_stmt().where(FileAsset.id == file_id)
    return (await db.execute(stmt)).first()


async def create_file_asset(
    db: AsyncSession,
    *,
    type: FileAssetType,
    s3_key: str,
    filename_display: str,
    content_type: str | None,
    size_bytes: int | None,
    brand_id: uuid.UUID | None,
    visibility: FileVisibility,
) -> FileAsset:
    asset = FileAsset(
        type=type,
        s3_key=s3_key,
        filename_display=filename_display,
        content_type=content_type,
        size_bytes=size_bytes,
        brand_id=brand_id,
        visibility=visibility,
    )
    db.add(asset)
    await db.flush()
    return asset


async def delete_file_asset(db: AsyncSession, asset: FileAsset) -> None:
    await db.delete(asset)
    await db.flush()
