"""Checks for checked-in API v2 contract and legacy migration artifacts."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

from app.api.v2.errors import PROBLEM_MEDIA_TYPE
from app.schemas.v2.catalog import CatalogFacets, CatalogProduct
from app.schemas.v2.common import (
    CursorResponse,
    Money,
    ProblemDetails,
    Rate,
    SuccessResponse,
)
from app.schemas.v2.cart import CartItemAdd, CartSummary
from app.schemas.v2.orders import OrderCreate, OrderDetail, OrderSummary
from app.schemas.v2.session import SessionContext
from app.scripts.export_v2_contract import v2_openapi_document

FIXTURES = Path(__file__).parent / "fixtures"


def _load(relative_path: str):
    return json.loads((FIXTURES / relative_path).read_text(encoding="utf-8"))


def test_v2_openapi_snapshot_matches_generated_v2_surface():
    snapshot = _load("openapi/api-v2.openapi.json")

    assert snapshot == v2_openapi_document()
    assert list(snapshot["paths"]) == [
        "/api/v2/cart",
        "/api/v2/cart/items",
        "/api/v2/cart/items/{productId}",
        "/api/v2/catalog/facets",
        "/api/v2/catalog/products",
        "/api/v2/catalog/products/by-sku/{sku}",
        "/api/v2/catalog/products/{productId}",
        "/api/v2/orders",
        "/api/v2/orders/{orderId}",
        "/api/v2/orders/{orderId}/cancel",
        "/api/v2/orders/{orderId}/repeat",
        "/api/v2/organizations",
        "/api/v2/organizations/{organizationId}",
        "/api/v2/organizations/{organizationId}/members",
        "/api/v2/organizations/{organizationId}/members/{userId}",
        "/api/v2/session",
        "/api/v2/session/organization",
    ]
    assert all(path.startswith("/api/v2") for path in snapshot["paths"])

    for path, path_item in snapshot["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if path.startswith(
                (
                    "/api/v2/cart",
                    "/api/v2/organizations",
                    "/api/v2/session",
                    "/api/v2/orders",
                )
            ) and not (method == "get" and path == "/api/v2/cart"):
                assert "422" in operation["responses"], (method, path)
            for status, response in operation["responses"].items():
                if 200 <= int(status) < 300:
                    continue
                content = response["content"]
                assert PROBLEM_MEDIA_TYPE in content, (method, path, status)
                assert content[PROBLEM_MEDIA_TYPE]["schema"] == {
                    "$ref": "#/components/schemas/ProblemDetails"
                }

    if_match = next(
        parameter
        for parameter in snapshot["paths"][
            "/api/v2/organizations/{organizationId}/members/{userId}"
        ]["patch"]["parameters"]
        if parameter["name"] == "If-Match"
    )
    assert if_match["in"] == "header"
    assert if_match["required"] is True
    for path, method in (
        ("/api/v2/cart/items", "post"),
        ("/api/v2/cart/items/{productId}", "put"),
        ("/api/v2/cart/items/{productId}", "delete"),
        ("/api/v2/cart", "delete"),
        ("/api/v2/orders/{orderId}/repeat", "post"),
    ):
        parameter = next(
            item
            for item in snapshot["paths"][path][method]["parameters"]
            if item["name"] == "If-Match"
        )
        assert parameter["required"] is True, (path, method)
    assert "HTTPValidationError" not in snapshot.get("components", {}).get(
        "schemas", {}
    )


def test_shared_v2_json_fixtures_match_pydantic_contract():
    money = Money.model_validate(_load("v2/money.json"))
    rate = Rate.model_validate(_load("v2/rate.json"))
    success = SuccessResponse[OrderDetail].model_validate(
        _load("v2/order_detail_success.json")
    )
    create_request = OrderCreate.model_validate(
        _load("v2/order_create_request.json")
    )
    create_success = SuccessResponse[OrderDetail].model_validate(
        _load("v2/order_create_success.json")
    )
    order_page = CursorResponse[OrderSummary].model_validate(
        _load("v2/order_list_page.json")
    )
    cart = SuccessResponse[CartSummary].model_validate(
        _load("v2/cart_repeat_success.json")
    )
    cart_get = SuccessResponse[CartSummary].model_validate(
        _load("v2/cart_get_success.json")
    )
    cart_add = CartItemAdd.model_validate(_load("v2/cart_item_add_request.json"))
    not_found = ProblemDetails.model_validate(_load("v2/problem_order_not_found.json"))
    stale_cart = ProblemDetails.model_validate(
        _load("v2/problem_stale_cart_version.json")
    )
    validation = ProblemDetails.model_validate(_load("v2/problem_validation_error.json"))
    session = SuccessResponse[SessionContext].model_validate(
        _load("v2/session_success.json")
    )
    catalog_page = CursorResponse[CatalogProduct].model_validate(
        _load("v2/catalog_products_page.json")
    )
    facets = SuccessResponse[CatalogFacets].model_validate(
        _load("v2/catalog_facets.json")
    )

    assert money.amount == "294.90"
    assert rate.value == "1.0000"
    assert success.meta.request_id == "v2-fixture-order-detail-001"
    assert success.data.total == Money(amount="294.90", currency="BYN")
    assert create_request.items[0].quantity == "6"
    assert create_success.meta.request_id == "v2-fixture-order-create-001"
    assert create_success.data.organization_id is None
    assert create_success.data.delivery.address_id == uuid.UUID(
        "99999999-9999-4999-8999-999999999999"
    )
    assert order_page.meta.request_id == "v2-fixture-order-list-001"
    assert order_page.meta.has_more is False
    assert order_page.data[0].total == Money(amount="125.50", currency="BYN")
    assert order_page.data[0].status == "NEW"
    assert not hasattr(order_page.data[0], "lines")
    assert cart.data.version == 2
    assert cart.data.organization_id is None
    assert cart.data.exchange_rate == Rate(value="1.0000", scale=4, source="BYN")
    assert cart.data.total_items == 1
    assert cart.data.total == Money(amount="40.00", currency="BYN")
    assert not hasattr(cart.data.items[0], "photo_key")
    assert cart_get.data.organization_id == uuid.UUID(
        "77777777-7777-4777-8777-777777777777"
    )
    assert cart_get.data.exchange_rate == Rate(value="2.0000", scale=4, source="FIXED")
    assert cart_add.quantity == "2"
    assert stale_cart.code == "STALE_RESOURCE_VERSION"
    assert not_found.code == "ORDER_NOT_FOUND"
    assert validation.code == "VALIDATION_ERROR"
    assert validation.errors[0].field == "orderId"
    assert session.data.commercial_scope == "USER"
    assert session.data.organization_id is None
    assert catalog_page.data[0].client_price == Money(amount="90.00", currency="BYN")
    assert catalog_page.meta.has_more is False
    assert facets.data.models == ["Аксессуары"]


def test_legacy_migration_fixture_is_deterministic_and_representative():
    fixture = _load("legacy/price_web_legacy_v1.json")
    data = fixture["data"]

    assert fixture["sourceMigration"] == "0009_carts_unique_orders_seq"
    assert fixture["migrationExpectations"]["doNotAutoMerge"] == ["users.company"]
    assert "organization_id" not in fixture["migrationExpectations"]["backfillLater"]

    user_ids = {row["id"] for row in data["users"]}
    assert len(user_ids) == len(data["users"])
    assert len({row["email"] for row in data["users"]}) == len(data["users"])
    assert {row["company"] for row in data["users"] if row["role"] == "CLIENT"} == {
        "СтройТрейд"
    }

    for user in data["users"]:
        uuid.UUID(user["id"])
    for brand in data["brands"]:
        uuid.UUID(brand["id"])
    for series in data["series"]:
        uuid.UUID(series["id"])
        assert series["brand_id"] in {brand["id"] for brand in data["brands"]}
    for product in data["products"]:
        uuid.UUID(product["id"])
        assert product["brand_id"] in {brand["id"] for brand in data["brands"]}
        assert product["series_id"] in {series["id"] for series in data["series"]}

    orders_by_id = {order["id"]: order for order in data["orders"]}
    assert [order["seq"] for order in data["orders"]] == [41, 42]
    for order in data["orders"]:
        uuid.UUID(order["id"])
        assert order["client_id"] in user_ids
        assert order["manager_id"] is None or order["manager_id"] in user_ids
        assert "delivery_address" not in order
        assert "idempotency_key" not in order
        assert "version" not in order

    order_totals: dict[str, Decimal] = {order_id: Decimal("0") for order_id in orders_by_id}
    for item in data["order_items"]:
        uuid.UUID(item["id"])
        assert item["order_id"] in orders_by_id
        assert item["product_id"] in {product["id"] for product in data["products"]}
        order_totals[item["order_id"]] += Decimal(item["unit_price"]) * item["quantity"]

    for order_id, total in order_totals.items():
        assert total == Decimal(orders_by_id[order_id]["total_amount"])
