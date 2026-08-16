"""Роутер каталога/прайса. См. ARCHITECTURE_PLAN.md §6, SITEMAP §6.

Все эндпоинты требуют авторизации (каталог — для клиентов/менеджеров).
Цены рассчитываются под текущего пользователя (§8, §17).
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories import catalog as repo
from app.schemas import MetaPage
from app.schemas.catalog import (
    BrandRef,
    CatalogPage,
    FiltersOut,
    PriceHistoryItem,
    ProductCard,
    ProductDetail,
    SeriesRef,
)
from app.services.cache import (
    CATALOG_TAG,
    FILTERS_TAG,
    cache,
    catalog_key,
    product_key,
    stable_hash,
    user_tag,
)
from app.services.pricing import PricingService

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products", response_model=CatalogPage)
async def list_products(
    q: str | None = Query(default=None, description="Поиск по артикулу/наименованию"),
    brand: list[uuid.UUID] | None = Query(default=None),
    series: list[uuid.UUID] | None = Query(default=None),
    stock: Literal["IN_STOCK", "PREORDER"] | None = None,
    price_calc_mode: Literal["fixed", "nbrb_current"] = Query(
        default="fixed", description="fixed=по договору, nbrb_current=по текущему НБ РБ"
    ),
    sort: Literal["name", "-name", "price", "-price", "sku"] = "name",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CatalogPage:
    filters = repo.CatalogFilters(
        q=q, brand_ids=brand, series_ids=series, stock=stock
    )
    key = catalog_key(
        user_id=user.id,
        mode=price_calc_mode,
        filters={
            "q": q,
            "brand": sorted(str(v) for v in (brand or [])),
            "series": sorted(str(v) for v in (series or [])),
            "stock": stock,
            "sort": sort,
            "page": page,
            "per_page": per_page,
        },
    )
    cached = await cache.safe_get(key)
    if cached is not None:
        return CatalogPage.model_validate(cached)

    limit, offset = per_page, (page - 1) * per_page

    rows = await repo.fetch_catalog(
        db, user_id=user.id, filters=filters, sort=sort, limit=limit, offset=offset
    )
    total = await repo.count_catalog(db, filters=filters)

    pricing = PricingService(db)
    cards: list[ProductCard] = []
    for row in rows:
        product = row[0]
        prices = await pricing.price_product(product, user, price_calc_mode)
        cards.append(
            ProductCard(
                id=product.id,
                sku=product.sku,
                name=product.name,
                brand=BrandRef(id=row.brand_id, name=row.brand_name) if row.brand_id else None,
                series=(
                    SeriesRef(id=row.series_id, name=row.series_name, photo_key=row.photo_key)
                    if row.series_id
                    else None
                ),
                stock_status=product.stock_status,
                photo_key=row.photo_key,
                attributes=product.attributes or {},
                **prices,
            )
        )

    result = CatalogPage(data=cards, meta=MetaPage(page=page, per_page=per_page, total=total))
    await cache.safe_set(
        key,
        result.model_dump(mode="json"),
        ttl=settings.cache_ttl_seconds,
        tags=[CATALOG_TAG, user_tag(user.id)],
    )
    return result


@router.get("/filters", response_model=FiltersOut)
async def get_filters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FiltersOut:
    key = f"filters:{stable_hash({})}"
    cached = await cache.safe_get(key)
    if cached is not None:
        return FiltersOut.model_validate(cached)
    data = await repo.fetch_filters(db)
    result = FiltersOut(**data)
    await cache.safe_set(
        key,
        result.model_dump(mode="json"),
        ttl=settings.cache_ttl_seconds,
        tags=[FILTERS_TAG],
    )
    return result


@router.get("/products/{sku}", response_model=ProductDetail)
async def get_product(
    sku: str,
    price_calc_mode: Literal["fixed", "nbrb_current"] = "fixed",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProductDetail:
    key = product_key(user_id=user.id, mode=price_calc_mode, sku=sku)
    cached = await cache.safe_get(key)
    if cached is not None:
        return ProductDetail.model_validate(cached)

    product = await repo.get_by_sku(db, sku)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")

    pricing = PricingService(db)
    prices = await pricing.price_product(product, user, price_calc_mode)

    brand = None
    if product.brand_id:
        b = await repo.get_brand(db, product.brand_id)
        if b:
            brand = BrandRef(id=b.id, name=b.name)

    series = None
    if product.series_id:
        s = await repo.get_series(db, product.series_id)
        if s:
            series = SeriesRef(id=s.id, name=s.name, brand_id=s.brand_id, photo_key=s.photo_key)

    result = ProductDetail(
        id=product.id,
        sku=product.sku,
        name=product.name,
        brand=brand,
        series=series,
        stock_status=product.stock_status,
        photo_key=series.photo_key if series else None,
        attributes=product.attributes or {},
        override_price=float(product.override_price) if product.override_price is not None else None,
        **prices,
    )
    await cache.safe_set(
        key,
        result.model_dump(mode="json"),
        ttl=settings.cache_ttl_seconds,
        tags=[CATALOG_TAG, user_tag(user.id)],
    )
    return result


@router.get("/products/{sku}/price-history", response_model=list[PriceHistoryItem])
async def get_price_history(
    sku: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PriceHistoryItem]:
    product = await repo.get_by_sku(db, sku)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    rows = await repo.fetch_price_history(db, product.id)
    return [
        PriceHistoryItem(
            base_price=float(r.base_price),
            override_price=float(r.override_price) if r.override_price is not None else None,
            changed_at=r.changed_at.isoformat(),
        )
        for r in rows
    ]
