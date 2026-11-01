"""Persistence for client SKU mappings (§16 п.43).

CITEXT-нормализацию сравнения делает сама колонка (регистр не важен); trim
артикула выполняет сервис до вызова репозитория.
"""
import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.client_sku import ClientSkuMapping


def _search_filter(query: str) -> ColumnElement[bool]:
    """Подстрочный поиск по артикулу клиента и по нашему SKU (ILIKE, §5.2)."""
    pattern = f"%{query}%"
    return or_(
        ClientSkuMapping.client_sku.ilike(pattern),
        Product.sku.ilike(pattern),
    )


def _list_statement(
    *, organization_id: uuid.UUID, query: str | None
):
    stmt = (
        select(ClientSkuMapping)
        .outerjoin(Product, Product.id == ClientSkuMapping.product_id)
        .where(ClientSkuMapping.organization_id == organization_id)
    )
    if query:
        stmt = stmt.where(_search_filter(query))
    return stmt


def _count_statement(
    *, organization_id: uuid.UUID, query: str | None
):
    stmt = (
        select(func.count())
        .select_from(ClientSkuMapping)
        .outerjoin(Product, Product.id == ClientSkuMapping.product_id)
        .where(ClientSkuMapping.organization_id == organization_id)
    )
    if query:
        stmt = stmt.where(_search_filter(query))
    return stmt


async def get(
    db: AsyncSession, *, organization_id: uuid.UUID, mapping_id: uuid.UUID
) -> ClientSkuMapping | None:
    """Маппинг по PK в пределах организации (чужой PK виден как 404)."""
    return await db.scalar(
        select(ClientSkuMapping).where(
            ClientSkuMapping.id == mapping_id,
            ClientSkuMapping.organization_id == organization_id,
        )
    )


async def get_by_sku(
    db: AsyncSession, *, organization_id: uuid.UUID, client_sku: str
) -> ClientSkuMapping | None:
    """Связка по артикулу клиента (CITEXT — регистр не важен)."""
    return await db.scalar(
        select(ClientSkuMapping).where(
            ClientSkuMapping.organization_id == organization_id,
            ClientSkuMapping.client_sku == client_sku,
        )
    )


async def get_by_skus(
    db: AsyncSession, *, organization_id: uuid.UUID, client_skus: list[str]
) -> dict[str, ClientSkuMapping]:
    """Связки по списку артикулов одним IN-запросом (для apply-csv).

    Возвращает ``{client_sku_lower: ClientSkuMapping}``; CITEXT-уникальность
    гарантирует, что двух связок, совпадающих без регистра, не существует.
    """
    if not client_skus:
        return {}
    res = await db.scalars(
        select(ClientSkuMapping).where(
            ClientSkuMapping.organization_id == organization_id,
            ClientSkuMapping.client_sku.in_(client_skus),
        )
    )
    return {mapping.client_sku.lower(): mapping for mapping in res.all()}


async def list_page(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[ClientSkuMapping]:
    """Страница справочника, свежие сверху (индекс org + created_at DESC)."""
    stmt = _list_statement(organization_id=organization_id, query=query).order_by(
        ClientSkuMapping.created_at.desc(), ClientSkuMapping.id.desc()
    )
    if offset:
        stmt = stmt.offset(offset)
    stmt = stmt.limit(limit)
    res = await db.scalars(stmt)
    return list(res.all())


async def count(
    db: AsyncSession, *, organization_id: uuid.UUID, query: str | None = None
) -> int:
    return int(
        await db.scalar(
            _count_statement(organization_id=organization_id, query=query)
        )
        or 0
    )


async def get_products_by_ids(
    db: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Product]:
    """Живые (не удалённые) товары по UUID одним IN-запросом — для отчёта apply-csv.

    ARCHIVED не отфильтровываем: строка отчёта обязана отличать «Товар в
    архиве» (§16 п.43 п.4) от «Не найден в справочнике».
    """
    if not product_ids:
        return {}
    res = await db.scalars(
        select(Product).where(
            Product.id.in_(product_ids), Product.deleted_at.is_(None)
        )
    )
    return {product.id: product for product in res.all()}


async def create(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    client_sku: str,
    product_id: uuid.UUID,
    note: str | None,
) -> ClientSkuMapping:
    mapping = ClientSkuMapping(
        organization_id=organization_id,
        client_sku=client_sku,
        product_id=product_id,
        note=note,
    )
    db.add(mapping)
    await db.flush()
    return mapping


async def update(
    db: AsyncSession, *, mapping: ClientSkuMapping, changes: dict[str, object]
) -> ClientSkuMapping:
    for field, value in changes.items():
        setattr(mapping, field, value)
    mapping.version += 1
    await db.flush()
    return mapping


async def delete(db: AsyncSession, *, mapping: ClientSkuMapping) -> None:
    await db.delete(mapping)
    await db.flush()


__all__ = [
    "count",
    "create",
    "delete",
    "get",
    "get_by_sku",
    "get_by_skus",
    "get_products_by_ids",
    "list_page",
    "update",
]
