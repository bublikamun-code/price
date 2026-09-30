"""Read-only API v2 catalog endpoints.

This slice reuses the v1 repository and PricingService on purpose: v2 changes
transport and DTO shape, not commercial calculations, visibility rules, or
personalized terms.  Organization ownership and media resources remain
provisional until their dedicated contracts are available.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import V2ProblemError, problem_responses, request_id_for
from app.api.v2.pagination import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    filter_signature,
)
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import StockStatus
from app.models.user import User
from app.repositories import catalog as repo
from app.repositories import file_assets as file_assets_repo
from app.schemas.v2.catalog import (
    BrandRef,
    CatalogFacets,
    CatalogProduct,
    SeriesRef,
    VolumeTierHint,
)
from app.schemas.v2.common import (
    RATE_SCALE,
    CursorMeta,
    CursorResponse,
    Money,
    Rate,
    ResponseMeta,
    SuccessResponse,
    rate_value,
)
from app.schemas.v2.documents import ProductDocument
from app.schemas.v2.media import MediaResource
from app.services import media as media_service
from app.services.organizations import OrganizationContextService
from app.services.pricing import PricingService, ResolvedRate

router = APIRouter(prefix="/catalog", tags=["catalog"])

_SORT = Literal["name", "-name", "price", "-price", "sku"]
_STOCK = Literal["IN_STOCK", "PREORDER"]


def _problem(status: int, *, code: str, title: str, detail: str) -> V2ProblemError:
    return V2ProblemError(code=code, status=status, title=title, detail=detail)


_CATALOG_CURSOR_RESOURCE = "catalog.products"


def _catalog_filter_signature(
    user: User,
    context,
    *,
    q: str | None,
    brands: list[uuid.UUID] | None,
    series: list[uuid.UUID] | None,
    stock: str | None,
    model: str | None,
) -> str:
    """Подпись набора фильтров страницы.

    Курсор выдан для конкретного списка: продолжить его с другими фильтрами
    нельзя, иначе клиент получит страницу, выпадающую из своей выборки
    (API_V2_CONTRACT § «pagination»). Списки id приводим к канонической строке,
    чтобы порядок повторений в query-параметрах не ломал подпись.
    """
    def _ids(values: list[uuid.UUID] | None) -> str | None:
        if not values:
            return None
        return ",".join(sorted({str(value) for value in values}))

    return filter_signature(
        str(user.id),
        str(context.organization_id) if context.organization_id else None,
        q.strip() if q is not None else None,
        _ids(brands),
        _ids(series),
        stock,
        model.strip() if model is not None else None,
    )


def _encode_catalog_cursor(
    sort: str,
    product,
    *,
    filter_sig: str,
) -> str:
    value = {
        "name": product.name,
        "sku": product.sku,
        "price": format(Decimal(str(product.base_price)), "f"),
    }[sort.lstrip("-")]
    return encode_cursor(
        resource=_CATALOG_CURSOR_RESOURCE,
        sort=sort,
        filter_sig=filter_sig,
        value=value,
        item_id=product.id,
    )


def _decode_catalog_cursor(
    cursor: str | None,
    *,
    sort: str,
    filter_sig: str,
) -> dict[str, str] | None:
    if cursor is None:
        return None
    try:
        decoded = decode_cursor(
            cursor,
            resource=_CATALOG_CURSOR_RESOURCE,
            sort=sort,
            filter_sig=filter_sig,
        )
        # Подпись проверена целиком; дальше валидируем только ключ сортировки,
        # который репозиторий будет разбирать в SQL-условие.
        if sort.lstrip("-") == "price":
            Decimal(decoded["value"])
        return decoded
    except (InvalidCursorError, ValueError, TypeError, ArithmeticError) as exc:
        raise _problem(
            422,
            code="VALIDATION_ERROR",
            title="Ошибка валидации",
            detail="Курсор пагинации недействителен",
        ) from exc


def _filters(
    *,
    q: str | None,
    brands: list[uuid.UUID] | None,
    series: list[uuid.UUID] | None,
    stock: str | None,
    model: str | None,
) -> repo.CatalogFilters:
    return repo.CatalogFilters(
        q=q,
        brand_ids=brands,
        series_ids=series,
        stock=StockStatus(stock) if stock else None,
        model=model,
    )


def _rate(resolved: ResolvedRate) -> Rate:
    return Rate(
        value=rate_value(resolved.rate if resolved.rate is not None else Decimal("1")),
        scale=resolved.scale if resolved.rate is not None else RATE_SCALE,
        source=resolved.source,
    )


def _product(row, prices: dict, resolved: ResolvedRate) -> CatalogProduct:
    product = row[0]
    # Репозиторий уже отдаёт photo_key (фото товара, иначе фото серии) — v2
    # превращает его в стабильный media-ресурс, S3-ключ наружу не уходит.
    # В БД лежит large-ключ, поэтому ссылка миниатюры несёт ``?size=thumb``:
    # эндпоинт отдаёт лежащий рядом кадр 400×400 ({stem}_thumb.webp, §16 п.17),
    # у старых загрузок без thumb — фолбэк на large (api/v2/media.py).
    thumbnail = media_service.media_ref_for_key(row.photo_key, thumb=True)
    return CatalogProduct(
        id=product.id,
        sku=product.sku,
        name=product.name,
        brand=BrandRef(id=row.brand_id, name=row.brand_name) if row.brand_id else None,
        series=(
            SeriesRef(id=row.series_id, name=row.series_name, brand_id=row.brand_id)
            if row.series_id and row.brand_id
            else None
        ),
        stock_status=(
            product.stock_status.value
            if hasattr(product.stock_status, "value")
            else str(product.stock_status)
        ),
        stock_quantity=product.stock_qty,
        attributes=product.attributes or {},
        base_price=Money.from_value(prices["base_price_byn"], currency="BYN"),
        retail_price=Money.from_value(prices["retail_price"], currency=resolved.currency),
        client_price=Money.from_value(prices["client_price"], currency=resolved.currency),
        exchange_rate=_rate(resolved),
        has_discount=prices["has_discount"],
        # Лестница за объём публикуется целиком: в каталоге количество ещё не
        # выбрано, поэтому объёмной скидки в clientPrice нет (§16 п.41 п.6).
        volume_tiers=[
            VolumeTierHint(
                min_qty=tier["min_qty"], discount_percent=tier["discount_percent"]
            )
            for tier in prices.get("volume_tiers", [])
        ],
        thumbnail=MediaResource.model_validate(thumbnail) if thumbnail else None,
    )


async def _gallery_media(db: AsyncSession, product_id: uuid.UUID) -> list[MediaResource]:
    """Кадры галереи товара (ProductPhoto, порядок sort_order/created_at).

    Оба detail-хендлера обязаны отдавать одинаковый набор: web-карточка
    открывается по by-sku, и без этого блока там оставалось только титульное
    фото, хотя by-productId показывал полную галерею.
    """
    gallery = await repo.list_product_photos(db, product_id)
    return [
        MediaResource.model_validate(ref)
        for ref in (media_service.media_ref_for_key(key) for key in gallery)
        if ref
    ]


async def _card_documents(db: AsyncSession, product) -> list[ProductDocument]:
    """Документы карточки товара (§16 п.38): свои + документы его серии.

    Просроченные приходят с ``is_expired=true`` — помечаем, не скрываем.
    Как и галерея, блок обязателен в обоих detail-хендлерах (карточка
    открывается и по by-sku).
    """
    assets = await file_assets_repo.fetch_product_documents(
        db, product_id=product.id, series_id=product.series_id
    )
    return [
        ProductDocument.from_asset(
            asset,
            scope="product" if asset.product_id == product.id else "series",
        )
        for asset in assets
    ]


@router.get(
    "/products",
    response_model=CursorResponse[CatalogProduct],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_products(
    request: Request,
    q: str | None = Query(default=None, description="Search by SKU or name"),
    brands: list[uuid.UUID] | None = Query(default=None),
    series: list[uuid.UUID] | None = Query(default=None),
    stock: _STOCK | None = None,
    model: str | None = Query(default=None),
    sort: _SORT = Query(default="name"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    price_calc_mode: Literal["fixed", "nbrb_current"] = Query(default="fixed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[CatalogProduct]:
    context = await OrganizationContextService(db).resolve(user)
    filter_sig = _catalog_filter_signature(
        user, context, q=q, brands=brands, series=series, stock=stock, model=model
    )
    after = _decode_catalog_cursor(cursor, sort=sort, filter_sig=filter_sig)
    rows = await repo.fetch_catalog_page(
        db,
        user_id=user.id,
        filters=_filters(q=q, brands=brands, series=series, stock=stock, model=model),
        sort=sort,
        limit=limit + 1,
        after=after,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    pricing = PricingService(db)
    resolved = await pricing.resolve_rate(
        user, price_calc_mode, organization_id=context.organization_id
    )
    products = [row[0] for row in rows]
    prices = await pricing.price_products(
        products,
        user,
        price_calc_mode,
        resolved=resolved,
        organization_id=context.organization_id,
    )
    data = [_product(row, prices[row[0].id], resolved) for row in rows]
    next_cursor = (
        _encode_catalog_cursor(
            sort,
            rows[-1][0],
            filter_sig=filter_sig,
        )
        if has_more and rows
        else None
    )
    return CursorResponse[CatalogProduct](
        data=data,
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=sort,
        ),
    )


@router.get(
    "/products/by-sku/{sku}",
    response_model=SuccessResponse[CatalogProduct],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Product not found",
            422: "Validation error",
        }
    ),
)
async def get_product_by_sku(
    request: Request,
    sku: str = Path(min_length=1, max_length=128),
    price_calc_mode: Literal["fixed", "nbrb_current"] = Query(default="fixed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CatalogProduct]:
    product = await repo.get_visible_by_sku(db, sku)
    if product is None:
        raise _problem(404, code="RESOURCE_NOT_FOUND", title="Товар не найден", detail="Товар не найден")
    row = await repo.get_catalog_row(db, user_id=user.id, product_id=product.id)
    if row is None:
        raise _problem(404, code="RESOURCE_NOT_FOUND", title="Товар не найден", detail="Товар не найден")
    context = await OrganizationContextService(db).resolve(user)
    pricing = PricingService(db)
    resolved = await pricing.resolve_rate(
        user, price_calc_mode, organization_id=context.organization_id
    )
    prices = await pricing.price_products(
        [product],
        user,
        price_calc_mode,
        resolved=resolved,
        organization_id=context.organization_id,
    )
    detail = _product(row, prices[product.id], resolved)
    detail.media = await _gallery_media(db, product.id)
    detail.documents = await _card_documents(db, product)
    return SuccessResponse[CatalogProduct](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/products/{productId}",
    response_model=SuccessResponse[CatalogProduct],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Product not found",
            422: "Validation error",
        }
    ),
)
async def get_product(
    request: Request,
    product_id: uuid.UUID = Path(alias="productId"),
    price_calc_mode: Literal["fixed", "nbrb_current"] = Query(default="fixed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CatalogProduct]:
    product = await repo.get_visible_by_id(db, product_id)
    if product is None:
        raise _problem(404, code="RESOURCE_NOT_FOUND", title="Товар не найден", detail="Товар не найден")
    # Раньше строка искалась через fetch_catalog_page(q=sku, sort="sku", limit=1):
    # это пересекалось с другими товарами по подстроке и молча возвращало чужую
    # строку, если limit=1 выпадал не на запрошенный SKU. get_catalog_row берёт
    # товар по точному PK — тот же путь, что у by-sku.
    row = await repo.get_catalog_row(db, user_id=user.id, product_id=product_id)
    if row is None:
        raise _problem(404, code="RESOURCE_NOT_FOUND", title="Товар не найден", detail="Товар не найден")
    pricing = PricingService(db)
    context = await OrganizationContextService(db).resolve(user)
    resolved = await pricing.resolve_rate(
        user, price_calc_mode, organization_id=context.organization_id
    )
    prices = await pricing.price_products(
        [product],
        user,
        price_calc_mode,
        resolved=resolved,
        organization_id=context.organization_id,
    )
    detail = _product(row, prices[product.id], resolved)
    detail.media = await _gallery_media(db, product_id)
    detail.documents = await _card_documents(db, product)
    return SuccessResponse[CatalogProduct](
        data=detail,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/facets",
    response_model=SuccessResponse[CatalogFacets],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            500: "Internal server error",
        }
    ),
)
async def get_facets(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[CatalogFacets]:
    del user  # visibility and pricing terms are not applied to this provisional aggregate
    values = await repo.fetch_filters(db)
    return SuccessResponse[CatalogFacets](
        data=CatalogFacets.model_validate(
            {
                "brands": values["brands"],
                "series": values["series"],
                "stock_statuses": values["stock"],
                "models": values["models"],
            }
        ),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )
