"""Репозиторий файлового архива (file_assets). См. ARCHITECTURE_PLAN.md §6
(files), §10 (S3), §16 п.18, §16 п.38 (документы на товар).

Только запросы к БД; валидация загрузки и S3 — в ``services/file_assets``.
``brand_name`` тянется через outerjoin на brands (для отображения).
Как и соседние репозитории — только ``flush``, коммитит роутер (§4).
"""
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand
from app.models.enums import FileAssetType, FileVisibility
from app.models.file import FileAsset

# Типы, попадающие в documents[] карточки товара (§16 п.38).
PRODUCT_DOCUMENT_TYPES = (FileAssetType.CERTIFICATE, FileAssetType.DATASHEET)


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
    product_id: uuid.UUID | None = None,
    series_id: uuid.UUID | None = None,
    valid_until: date | None = None,
) -> FileAsset:
    asset = FileAsset(
        type=type,
        s3_key=s3_key,
        filename_display=filename_display,
        content_type=content_type,
        size_bytes=size_bytes,
        brand_id=brand_id,
        product_id=product_id,
        series_id=series_id,
        valid_until=valid_until,
        visibility=visibility,
    )
    db.add(asset)
    await db.flush()
    return asset


def _card_scope_clause(product_id: uuid.UUID, series_id: uuid.UUID | None):
    """Документы карточки: свои (product_id) + документы серии товара.

    ``series_id is not None`` в условии исключает совпадение по NULL-колонке
    (SQL-сравнение с NULL не бывает истинным, но явная проверка читаемее).
    """
    clause = FileAsset.product_id == product_id
    if series_id is not None:
        # Скобки обязательны: `|` в Python связывает крепче `==`, и без них
        # условие превратилось бы в `(product_id = X OR series_id) == Y`.
        clause = clause | (FileAsset.series_id == series_id)
    return clause


async def fetch_product_documents(
    db: AsyncSession, *, product_id: uuid.UUID, series_id: uuid.UUID | None
) -> list[FileAsset]:
    """Документы карточки товара (§16 п.38): свои + документы его серии.

    Просроченные (``valid_until < today``) не отфильтровываются — при выдаче
    они помечаются ``is_expired``, а не скрываются.
    """
    stmt = (
        select(FileAsset)
        .where(
            FileAsset.type.in_(PRODUCT_DOCUMENT_TYPES),
            _card_scope_clause(product_id, series_id),
        )
        .order_by(FileAsset.created_at.desc(), FileAsset.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_product_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    product_id: uuid.UUID,
    series_id: uuid.UUID | None,
) -> FileAsset | None:
    """Документ по id, если он принадлежит товару или его серии."""
    stmt = (
        select(FileAsset)
        .where(
            FileAsset.id == document_id,
            FileAsset.type.in_(PRODUCT_DOCUMENT_TYPES),
            _card_scope_clause(product_id, series_id),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def delete_file_asset(db: AsyncSession, asset: FileAsset) -> None:
    await db.delete(asset)
    await db.flush()
