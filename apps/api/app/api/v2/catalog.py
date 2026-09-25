"""Read-only API v2 catalog endpoints.

This slice reuses the v1 repository and PricingService on purpose: v2 changes
transport and DTO shape, not commercial calculations, visibility rules, or
personalized terms.  Organization ownership and media resources remain
provisional until their dedicated contracts are available.
"""
from __future__ import annotations

import base64
import binascii
import json
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import V2ProblemError, problem_responses, request_id_for
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import StockStatus
from app.models.user import User
from app.repositories import catalog as repo
from app.schemas.v2.catalog import (
    BrandRef,
    CatalogFacets,
    CatalogProduct,
    SeriesRef,
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
from app.services.organizations import OrganizationContextService
from app.services.pricing import PricingService, ResolvedRate

router = APIRouter(prefix="/catalog", tags=["catalog"])

_SORT = Literal["name", "-name", "price", "-price", "sku"]
_STOCK = Literal["IN_STOCK", "PREORDER"]


def _problem(status: int, *, code: str, title: str, detail: str) -> V2ProblemError:
    return V2ProblemError(code=code, status=status, title=title, detail=detail)


def _encode_cursor(sort: str, product, *, organization_id: uuid.UUID | None) -> str:
    value = {
        "name": product.name,
        "sku": product.sku,
        "price": format(Decimal(str(product.base_price)), "f"),
    }[sort.lstrip("-")]
    payload = json.dumps(
        {
            "sort": sort,
            "scope": str(organization_id) if organization_id else "USER",
            "value": value,
            "id": str(product.id),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str, sort: str, *, organization_id: uuid.UUID | None
) -> dict[str, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("sort") != sort
            or payload.get("scope")
            != (str(organization_id) if organization_id else "USER")
            or not isinstance(payload.get("value"), str)
            or not isinstance(payload.get("id"), str)
        ):
            raise ValueError
        uuid.UUID(payload["id"])
        return {"sort": sort, "value": payload["value"], "id": payload["id"]}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error):
        raise _problem(
            422,
            code="VALIDATION_ERROR",
            title="Ошибка валидации",
            detail="Курсор пагинации недействителен",
        ) from None


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
    )


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
    after = (
        _decode_cursor(cursor, sort, organization_id=context.organization_id)
        if cursor
        else None
    )
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
        _encode_cursor(
            sort,
            rows[-1][0],
            organization_id=context.organization_id,
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
    return SuccessResponse[CatalogProduct](
        data=_product(row, prices[product.id], resolved),
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
    row = await repo.fetch_catalog_page(
        db,
        user_id=user.id,
        filters=repo.CatalogFilters(q=product.sku),
        sort="sku",
        limit=1,
    )
    if not row:
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
    return SuccessResponse[CatalogProduct](
        data=_product(row[0], prices[product.id], resolved),
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
