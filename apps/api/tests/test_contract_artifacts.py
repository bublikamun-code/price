"""Checks for checked-in API v2 contract and legacy migration artifacts."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

from app.api.v2.errors import PROBLEM_MEDIA_TYPE
from app.schemas.v2.auth import SessionGrant, SessionSummary, TwoFaChallenge
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
from app.schemas.v2.volume_tiers import VolumeTierOut
from app.scripts.export_v2_contract import v2_openapi_document

FIXTURES = Path(__file__).parent / "fixtures"


def _load(relative_path: str):
    return json.loads((FIXTURES / relative_path).read_text(encoding="utf-8"))


def test_v2_openapi_snapshot_matches_generated_v2_surface():
    snapshot = _load("openapi/api-v2.openapi.json")

    assert snapshot == v2_openapi_document()
    assert list(snapshot["paths"]) == [
        "/api/v2/auth/2fa/challenges/verify",
        "/api/v2/auth/sessions",
        "/api/v2/auth/sessions/current",
        "/api/v2/auth/sessions/refresh",
        "/api/v2/auth/sessions/{sessionId}",
        "/api/v2/cart",
        "/api/v2/cart/items",
        "/api/v2/cart/items/{productId}",
        "/api/v2/catalog/facets",
        "/api/v2/catalog/products",
        "/api/v2/catalog/products/by-sku/{sku}",
        "/api/v2/catalog/products/{productId}",
        "/api/v2/catalog/products/{productId}/documents/{documentId}/download",
        "/api/v2/manager/brands/{brandId}/volume-tiers",
        "/api/v2/manager/documents/{documentId}",
        "/api/v2/manager/invoices/{invoiceId}",
        "/api/v2/manager/invoices/{invoiceId}/pdf",
        "/api/v2/manager/orders/{orderId}/invoice",
        "/api/v2/manager/organizations/{id}",
        "/api/v2/manager/products/{productId}/documents",
        "/api/v2/manager/series/{seriesId}/documents",
        "/api/v2/manager/volume-tiers/{tierId}",
        "/api/v2/me/organization/addresses",
        "/api/v2/me/organization/addresses/{addressId}",
        "/api/v2/media/{mediaId}",
        "/api/v2/orders",
        "/api/v2/orders/invoices/{invoiceId}/download",
        "/api/v2/orders/{orderId}",
        "/api/v2/orders/{orderId}/cancel",
        "/api/v2/orders/{orderId}/invoice",
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
                    "/api/v2/auth",
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
    catalog_detail = SuccessResponse[CatalogProduct].model_validate(
        _load("v2/catalog_product_detail.json")
    )
    facets = SuccessResponse[CatalogFacets].model_validate(
        _load("v2/catalog_facets.json")
    )
    # Нативная аутентификация (§16 п.36). Эти фикстуры — единственный источник
    # правды для core/ (KMP): SwiftUI и Compose декодируют те же файлы, пока
    # нет кодогенератора из api-v2.openapi.json.
    grant = SuccessResponse[SessionGrant].model_validate(
        _load("v2/auth_session_grant.json")
    )
    challenge = SuccessResponse[TwoFaChallenge].model_validate(
        _load("v2/auth_two_fa_challenge.json")
    )
    journal = SuccessResponse[list[SessionSummary]].model_validate(
        _load("v2/auth_sessions_journal.json")
    )
    invalid_credentials = ProblemDetails.model_validate(
        _load("v2/problem_invalid_credentials.json")
    )
    tiers = SuccessResponse[list[VolumeTierOut]].model_validate(
        _load("v2/volume_tiers_list.json")
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

    # Media (§16 п.37): стабильный id + стабильный URL. Клиент кэширует по id,
    # поэтому presigned-подпись в контракт вообще не попадает.
    assert catalog_page.data[0].thumbnail is not None
    assert catalog_page.data[0].thumbnail.id == "44444444-4444-4444-8444-444444444444"
    assert catalog_page.data[0].thumbnail.url == (
        "/api/v2/media/44444444-4444-4444-8444-444444444444"
    )
    assert catalog_page.data[0].thumbnail.mime_type == "image/webp"
    # Список несёт только плитку — галерея пуста до детальной выборки.
    assert catalog_page.data[0].media == []
    assert len(catalog_detail.data.media) == 2
    assert catalog_detail.data.media[0].width == 1200
    # Галерея не обязана повторять thumbnail.
    assert catalog_detail.data.media[0].id != catalog_detail.data.thumbnail.id

    # Документы на товар (§16 п.38): свои + документы серии, просроченные
    # помечаются isExpired, а не скрываются. Скачивание — байтами через
    # v2-эндпоинт, поэтому presigned-ссылки в контракте нет вовсе.
    documents = catalog_detail.data.documents
    assert [(d.type, d.scope) for d in documents] == [
        ("CERTIFICATE", "product"),
        ("DATASHEET", "series"),
        ("CERTIFICATE", "product"),
    ]
    assert documents[0].file_name == "certificate-2026.pdf"
    assert str(documents[0].valid_until) == "2027-03-31"
    assert documents[0].is_expired is False
    assert documents[1].valid_until is None
    assert documents[2].is_expired is True
    assert not hasattr(documents[0], "s3_key")
    assert not hasattr(documents[0], "url")

    # Нативный grant: токены в теле, а не в cookie — это и есть отличие NATIVE от WEB.
    assert grant.meta.request_id == "v2-fixture-auth-grant-001"
    assert grant.data.refresh_token == "fixture-refresh-token-0001"
    assert grant.data.session.client_type == "NATIVE"
    assert grant.data.session.device_name == "iPhone 15 Pro"
    assert grant.data.session.os_name == "iOS 18.2"
    assert grant.data.session.current is True
    assert grant.data.user.email == "client@example.by"
    # Web-сессия в том же журнале не выдумывает устройство.
    assert journal.data[1].device_name is None
    assert journal.data[1].client_type == "WEB"
    assert [s.current for s in journal.data] == [True, False]
    assert challenge.data.two_fa_required is True
    assert not hasattr(challenge.data, "access_token")
    assert invalid_credentials.code == "INVALID_CREDENTIALS"
    assert invalid_credentials.status == 401

    # Скидки за объём (§16 п.41). Процент — число во всех трёх формах, а лестница
    # приходит по возрастанию minQty: UI выбирает ступень по количеству строки.
    assert tiers.meta.request_id == "v2-fixture-volume-tiers-001"
    assert [tier.min_qty for tier in tiers.data] == [10, 50]
    assert tiers.data[0].discount_percent == 2.0
    assert tiers.data[0].version == 1
    # Порог принадлежит бренду, а не товару: id шапки каталога один и тот же.
    assert tiers.data[1].brand_id == catalog_page.data[0].brand.id
    assert [hint.min_qty for hint in catalog_page.data[0].volume_tiers] == [10, 50]
    assert catalog_page.data[0].volume_tiers[0].discount_percent == 2.0
    # В корзине ступень уже применена к цене строки (2 шт × 19.00 = 38.00 USD).
    line = cart_get.data.items[0]
    assert line.volume_tier is not None
    assert line.volume_tier.min_qty == 2
    assert line.volume_tier.discount_percent == 5.0
    assert line.unit_price == Money(amount="19.00", currency="USD")
    assert line.line_total == Money(amount="38.00", currency="USD")
    assert cart_get.data.total == Money(amount="38.00", currency="USD")
    # Повтор заказа: лестницы у бренда нет — ступень null, цена не тронута.
    assert cart.data.items[0].volume_tier is None


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
