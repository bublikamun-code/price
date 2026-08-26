"""Роутер каталога/прайса. См. ARCHITECTURE_PLAN.md §6, SITEMAP §6.

Все эндпоинты требуют авторизации (каталог — для клиентов/менеджеров).
Цены рассчитываются под текущего пользователя (§8, §17).
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.limiter import EXPORT_RATE_LIMIT, export_rate_key, limiter
from app.db.session import get_db
from app.models.user import User
from app.repositories import catalog as repo
from app.schemas import MetaPage
from app.schemas.catalog import (
    BrandRef,
    BulkResolveIn,
    BulkResolveOut,
    BulkResolveRow,
    CatalogPage,
    ExportJobOut,
    ExportStartOut,
    FiltersOut,
    PriceHistoryItem,
    ProductCard,
    ProductDetail,
    ProductPrice,
    SeriesRef,
)
from app.services import export as export_service
from app.services import storage
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
                stock_qty=product.stock_qty,
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


@router.post("/resolve-bulk", response_model=BulkResolveOut)
async def resolve_bulk(
    payload: BulkResolveIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkResolveOut:
    """Проверка списка артикулов перед bulk-добавлением в корзину (§16 п.20-5).

    Ничего не добавляет: по каждой строке ввода (дубликаты — отдельные строки
    результата) возвращает товар с ценами под текущего пользователя либо
    ошибку «Товар не найден». Лимит: 1..500 позиций в запросе.
    """
    products = await repo.get_by_skus(db, [item.sku for item in payload.items])
    pricing = PricingService(db)

    rows: list[BulkResolveRow] = []
    for item in payload.items:
        product = products.get(item.sku)
        if product is None:
            rows.append(
                BulkResolveRow(
                    sku=item.sku, qty=item.qty, found=False, error="Товар не найден"
                )
            )
            continue
        prices = await pricing.price_product(product, user, "fixed")
        rows.append(
            BulkResolveRow(
                sku=item.sku,
                qty=item.qty,
                found=True,
                name=product.name,
                price=ProductPrice(**prices),
                stock_status=(
                    product.stock_status.value
                    if hasattr(product.stock_status, "value")
                    else str(product.stock_status)
                ),
            )
        )
    return BulkResolveOut(data=rows)


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
        stock_qty=product.stock_qty,
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


@router.post(
    "/export",
    response_model=ExportStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(EXPORT_RATE_LIMIT, key_func=export_rate_key)
async def start_catalog_export(
    request: Request,
    format: Literal["csv", "xlsx", "pdf"] = Query(description="Формат выгрузки"),
    q: str | None = Query(default=None, description="Поиск по артикулу/наименованию"),
    brand: list[uuid.UUID] | None = Query(default=None),
    series: list[uuid.UUID] | None = Query(default=None),
    stock: Literal["IN_STOCK", "PREORDER"] | None = None,
    price_calc_mode: Literal["fixed", "nbrb_current"] = Query(
        default="fixed", description="fixed=по договору, nbrb_current=по текущему НБ РБ"
    ),
    user: User = Depends(get_current_user),
) -> ExportStartOut:
    """Запустить экспорт каталога под текущие фильтры (CSV/XLSX/PDF, §16 п.16, п.25).

    Фильтры идентичны ``GET /catalog/products``; в файле — персональные цены
    пользователя. Файл собирает Celery-задача: статус опрашивается через
    ``GET /catalog/export/{job_id}``. Лимит: 10 запусков/час на пользователя.
    """
    filters = repo.CatalogFilters(q=q, brand_ids=brand, series_ids=series, stock=stock)
    job_id = await export_service.start_export(
        user=user, filters=filters, format=format, price_calc_mode=price_calc_mode
    )
    return ExportStartOut(job_id=job_id)


@router.get("/export/{job_id}", response_model=ExportJobOut)
async def get_export_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> ExportJobOut:
    """Статус job экспорта (только владелец, чужой/несуществующий → 404).

    ``url`` — presigned-ссылка на файл в S3 (5 мин), отдаётся только при DONE.
    """
    state = await export_service.get_job(user.id, job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Экспорт не найден"
        )
    url = None
    if state.get("status") == "DONE" and state.get("s3_key"):
        try:
            url = storage.presigned_get(settings.s3_bucket_exports, state["s3_key"])
        except storage.StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
    return ExportJobOut(
        job_id=state["job_id"],
        status=state["status"],
        format=state["format"],
        error=state.get("error"),
        url=url,
    )
