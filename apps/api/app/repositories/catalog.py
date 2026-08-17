"""Репозиторий каталога: запросы с фильтрами и пагинацией.

См. ARCHITECTURE_PLAN.md §6 (catalog endpoints), §5 (products).
Возвращает «сырые» строки; расчёт цен — в PricingService.
"""
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, PriceHistory, PriceListVersion, Product, Series
from app.models.enums import StockStatus
from app.models.pricing import UserBrand


@dataclass
class CatalogFilters:
    q: str | None = None
    brand_ids: Sequence[uuid.UUID] | None = None
    series_ids: Sequence[uuid.UUID] | None = None
    stock: StockStatus | None = None

    def has_any(self) -> bool:
        return any([self.q, self.brand_ids, self.series_ids, self.stock])


def _apply_catalog_filters(stmt, filters: CatalogFilters):
    """Общая WHERE-логика каталога (список / счётчик / экспорт)."""
    if filters.q:
        pat = f"%{filters.q}%"
        stmt = stmt.where(or_(Product.sku.ilike(pat), Product.name.ilike(pat)))
    if filters.brand_ids:
        stmt = stmt.where(Product.brand_id.in_(filters.brand_ids))
    if filters.series_ids:
        stmt = stmt.where(Product.series_id.in_(filters.series_ids))
    if filters.stock:
        stmt = stmt.where(Product.stock_status == filters.stock)
    return stmt


def _catalog_rows_stmt(user_id: uuid.UUID):
    """Базовый select каталога: товар + бренд/серия + скидка клиента."""
    return (
        select(
            Product,
            Brand.id.label("brand_id"),
            Brand.name.label("brand_name"),
            Brand.slug.label("brand_slug"),
            Series.id.label("series_id"),
            Series.name.label("series_name"),
            Series.photo_key.label("photo_key"),
            UserBrand.discount_percent.label("discount_percent"),
        )
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .outerjoin(Series, Series.id == Product.series_id)
        .outerjoin(
            UserBrand,
            (UserBrand.brand_id == Product.brand_id) & (UserBrand.user_id == user_id),
        )
        .where(Product.deleted_at.is_(None), Product.stock_status != StockStatus.ARCHIVED)
    )


async def fetch_catalog(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    filters: CatalogFilters,
    sort: str = "name",
    limit: int = 50,
    offset: int = 0,
):
    """Список товаров с брендом/серией/скидкой клиента. Возвращает list[Row]."""
    stmt = _apply_catalog_filters(_catalog_rows_stmt(user_id), filters)

    # сортировка
    sort_map = {
        "name": Product.name.asc(),
        "-name": Product.name.desc(),
        "price": Product.base_price.asc(),
        "-price": Product.base_price.desc(),
        "sku": Product.sku.asc(),
    }
    stmt = stmt.order_by(sort_map.get(sort, Product.name.asc()), Product.id.asc())

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.all()


async def fetch_catalog_all(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    filters: CatalogFilters,
):
    """Весь каталог под фильтры без пагинации (экспорт CSV/XLSX, §16 п.16).

    Та же WHERE-логика/джойны, что у ``fetch_catalog``, но без limit/offset —
    выгрузка отдаётся целиком в Celery-задачу экспорта. Строки те же:
    ``row[0]`` — ``Product``, плюс brand_name/series_name для колонок файла.
    """
    stmt = _apply_catalog_filters(_catalog_rows_stmt(user_id), filters).order_by(
        Product.name.asc(), Product.id.asc()
    )
    result = await db.execute(stmt)
    return result.all()


async def count_catalog(db: AsyncSession, *, filters: CatalogFilters) -> int:
    stmt = _apply_catalog_filters(
        select(func.count(Product.id)).where(
            Product.deleted_at.is_(None), Product.stock_status != StockStatus.ARCHIVED
        ),
        filters,
    )
    return int(await db.scalar(stmt) or 0)


async def get_by_sku(db: AsyncSession, sku: str) -> Product | None:
    return await db.scalar(
        select(Product).where(Product.sku == sku, Product.deleted_at.is_(None))
    )


async def get_brand(db: AsyncSession, brand_id: uuid.UUID) -> Brand | None:
    return await db.scalar(select(Brand).where(Brand.id == brand_id))


async def get_series(db: AsyncSession, series_id: uuid.UUID) -> Series | None:
    return await db.scalar(select(Series).where(Series.id == series_id))


async def fetch_filters(db: AsyncSession) -> dict:
    """Доступные значения фильтров (бренды, серии, статусы)."""
    brands = (
        await db.execute(
            select(Brand.id, Brand.name).order_by(Brand.name)
        )
    ).all()
    series = (
        await db.execute(
            select(Series.id, Series.name, Series.brand_id).order_by(Series.name)
        )
    ).all()
    stocks = (
        await db.execute(
            select(Product.stock_status)
            .where(Product.deleted_at.is_(None), Product.stock_status != StockStatus.ARCHIVED)
            .distinct()
        )
    ).all()
    return {
        "brands": [{"id": str(b.id), "name": b.name} for b in brands],
        "series": [
            {"id": str(s.id), "name": s.name, "brand_id": str(s.brand_id)} for s in series
        ],
        "stock": [s[0].value for s in stocks],
    }


async def fetch_price_history(
    db: AsyncSession, product_id: uuid.UUID, limit: int = 50
):
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.changed_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ----------------------------- write-хелперы -----------------------------
# Используются seed-скриптами и (в будущем) импортом прайса (Этап 4).
# get_or_create/upsert — idempotent: безопасны к повторному запуску.


def _slugify(name: str) -> str:
    return name.lower().strip().replace(" ", "-")


async def get_or_create_brand(
    db: AsyncSession, *, name: str, slug: str | None = None
) -> Brand:
    slug = slug or _slugify(name)
    brand = await db.scalar(select(Brand).where(Brand.slug == slug))
    if brand is not None:
        return brand
    brand = Brand(name=name, slug=slug)
    db.add(brand)
    await db.flush()
    return brand


async def get_or_create_series(
    db: AsyncSession,
    *,
    name: str,
    brand_id: uuid.UUID,
    photo_key: str | None = None,
) -> Series:
    series = await db.scalar(
        select(Series).where(Series.name == name, Series.brand_id == brand_id)
    )
    if series is not None:
        # Дозаполняем фото, если ранее серия была без него.
        if photo_key and not series.photo_key:
            series.photo_key = photo_key
            await db.flush()
        return series
    series = Series(name=name, brand_id=brand_id, photo_key=photo_key)
    db.add(series)
    await db.flush()
    return series


async def upsert_product(
    db: AsyncSession,
    *,
    sku: str,
    name: str,
    brand_id: uuid.UUID | None,
    series_id: uuid.UUID | None,
    base_price,
    attributes: dict | None = None,
    stock_status: StockStatus = StockStatus.IN_STOCK,
    price_list_version_id: uuid.UUID | None = None,
    override_price: Decimal | None = None,
    update_override: bool = False,
) -> tuple[Product, bool]:
    """Создать или обновить товар по ``sku`` (среди не удалённых).

    Возвращает ``(product, created)``. Матч — по артикулу среди активных
    (deleted_at IS NULL). При обновлении перезаписывает поля из источника.

    ``override_price`` (§8, §16 п.3): обновляется только когда
    ``update_override=True`` (т.е. CSV дал ``discount_price``). Иначе ранее
    заданное менеджером значение сохраняется — импорт не разрушает ручные скидки.
    """
    product = await db.scalar(
        select(Product).where(Product.sku == sku, Product.deleted_at.is_(None))
    )
    if product is not None:
        product.name = name
        product.brand_id = brand_id
        product.series_id = series_id
        product.base_price = base_price
        product.attributes = attributes or {}
        product.stock_status = stock_status
        product.price_list_version_id = price_list_version_id
        if update_override:
            product.override_price = override_price
        await db.flush()
        return product, False
    product = Product(
        sku=sku,
        name=name,
        brand_id=brand_id,
        series_id=series_id,
        base_price=base_price,
        attributes=attributes or {},
        stock_status=stock_status,
        price_list_version_id=price_list_version_id,
        override_price=override_price if update_override else None,
    )
    db.add(product)
    await db.flush()
    return product, True


async def archive_missing(db: AsyncSession, *, keep_skus: set[str]) -> int:
    """Soft-delete товаров, чей ``sku`` не входит в ``keep_skus`` (§7.2 шаг 4).

    Режим ``ARCHIVE_MISSING``: помечаем ``deleted_at=now()`` и
    ``stock_status=ARCHIVED``. Возвращает кол-во затронутых строк.
    Пустой ``keep_skus`` намеренно не архивирует весь каталог — для полной
    очистки используйте отдельный инструмент (защита от случайного вытирания).
    """
    if not keep_skus:
        return 0
    stmt = (
        update(Product)
        .where(Product.deleted_at.is_(None), Product.sku.notin_(keep_skus))
        .values(deleted_at=func.now(), stock_status=StockStatus.ARCHIVED)
    )
    result = await db.execute(stmt)
    await db.flush()
    return int(result.rowcount or 0)


async def add_price_history(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    base_price,
    override_price: Decimal | None,
    price_list_version_id: uuid.UUID | None = None,
) -> None:
    """Записать снимок цены товара при импорте (§16.1 фича J).

    История пишется всегда при upsert из прайс-листа — основа для будущего
    ``PRICE_CHANGED_DIGEST`` (Этап 6) и аудита изменений цен.
    """
    db.add(
        PriceHistory(
            product_id=product_id,
            base_price=base_price,
            override_price=override_price,
            price_list_version_id=price_list_version_id,
        )
    )
    await db.flush()


# ----------------------------- price-list versions -----------------------------

async def fetch_price_list_versions(
    db: AsyncSession, *, limit: int, offset: int
) -> tuple[list[PriceListVersion], int]:
    """Список версий импорта (новые первыми) + общее кол-во."""
    total = await db.scalar(select(func.count(PriceListVersion.id)))
    stmt = (
        select(PriceListVersion)
        .order_by(PriceListVersion.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.scalars(stmt)).all()
    return list(rows), int(total or 0)


async def get_price_list_version(
    db: AsyncSession, version_id: uuid.UUID
) -> PriceListVersion | None:
    return await db.scalar(
        select(PriceListVersion).where(PriceListVersion.id == version_id)
    )


# ----------------------------- rollback версии -----------------------------

# Restore: последним (changed_at DESC) «чужим» снапшотом вернуть цены и версию.
_RESTORE_SQL = text("""
    WITH last_snapshot AS (
        SELECT DISTINCT ON (ph.product_id)
               ph.product_id, ph.base_price, ph.override_price,
               ph.price_list_version_id
        FROM price_history ph
        WHERE ph.price_list_version_id != :vid
          -- push-down: DISTINCT ON только по товарам версии (иначе full scan
          -- истории); индекс ix_price_history_product_time ведёт поиск
          AND ph.product_id IN (
              SELECT id FROM products WHERE price_list_version_id = :vid
          )
        ORDER BY ph.product_id, ph.changed_at DESC
    )
    UPDATE products p
    SET base_price = ls.base_price,
        override_price = ls.override_price,
        price_list_version_id = ls.price_list_version_id,
        updated_at = now()
    FROM last_snapshot ls
    WHERE p.id = ls.product_id
      AND p.price_list_version_id = :vid
      AND p.deleted_at IS NULL
""")

# Archive: товары версии без «чужих» снапшотов (впервые появились в ней).
_ARCHIVE_SQL = text("""
    UPDATE products p
    SET deleted_at = now(),
        stock_status = 'ARCHIVED',
        updated_at = now()
    WHERE p.price_list_version_id = :vid
      AND p.deleted_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM price_history ph
          WHERE ph.product_id = p.id
            AND ph.price_list_version_id != :vid
      )
""")


async def rollback_version(
    db: AsyncSession, version_id: uuid.UUID
) -> tuple[int, int]:
    """Откат версии прайса на уровне каталога (§16 п.14), set-based SQL.

    Два statement'а, порядок важен (restore первым — восстановленные товары
    перестают принадлежать версии и в archive не попадают):
      1. restore — товарам версии ``version_id`` (не удалённым), у которых есть
         снапшот ``price_history`` другой версии, вернуть ``base_price`` /
         ``override_price`` последнего такого снапшота и его версию;
      2. archive — товарам версии без снапшотов других версий (впервые
         появились в ней) — soft-delete: ``deleted_at=now()``,
         ``stock_status='ARCHIVED'``.

    Возвращает ``(restored, archived)``. Не коммитит — транзакцией владеет
    сервис (``services.price_list_import.rollback_version``).
    """
    restore = await db.execute(_RESTORE_SQL, {"vid": version_id})
    restored = int(restore.rowcount or 0)

    archive = await db.execute(_ARCHIVE_SQL, {"vid": version_id})
    archived = int(archive.rowcount or 0)

    await db.flush()
    return restored, archived

