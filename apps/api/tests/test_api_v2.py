"""Contract tests for the first API v2 vertical slice."""
import uuid

from app.models.enums import UserRole
from app.schemas.v2.common import Money, money_amount, rate_value
from tests.conftest import (
    create_brand,
    create_product,
    create_user,
    set_discount,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "v2-client@example.by"


async def _login(api_client):
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": CLIENT_EMAIL, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def test_money_and_rate_are_fixed_decimal_strings():
    assert money_amount("12.345") == "12.35"
    assert money_amount(0.1) == "0.10"
    assert rate_value(3) == "3.0000"

    money = Money(amount="12.3", currency="BYN")
    assert money.model_dump(mode="json", by_alias=True) == {
        "amount": "12.30",
        "currency": "BYN",
    }


async def test_v2_order_detail_uses_success_envelope_and_string_money(
    api_client, session_factory
):
    brand = await create_brand(session_factory, name="V2 Brand")
    await create_product(
        session_factory,
        sku="V2-1",
        name="V2 Widget",
        brand=brand,
        base_price=100,
    )
    await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    created = await api_client.post(
        "/api/v1/orders",
        json={
            "items": [{"sku": "V2-1", "quantity": 3}],
            "delivery_point": "Склад Минск",
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    request_id = "v2-contract-order-001"
    response = await api_client.get(
        f"/api/v2/orders/{order_id}",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"] == request_id
    body = response.json()
    assert body["meta"]["requestId"] == request_id
    data = body["data"]
    assert data["id"] == order_id
    assert data["total"] == {"amount": "300.00", "currency": "BYN"}
    assert data["exchangeRate"] == {
        "value": "1.0000",
        "scale": 4,
        "source": "BYN",
    }
    assert data["lines"][0]["sku"] == "V2-1"
    assert data["lines"][0]["unitPrice"]["amount"] == "100.00"
    assert data["lines"][0]["lineTotal"]["amount"] == "300.00"
    assert "unit_price" not in data
    assert "total_amount" not in data


async def test_v2_missing_order_returns_problem_details(api_client, session_factory):
    await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    order_id = uuid.uuid4()
    request_id = "v2-contract-missing-001"
    response = await api_client.get(
        f"/api/v2/orders/{order_id}",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 404, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/order-not-found")
    assert body["title"] == "Заявка не найдена"
    assert body["status"] == 404
    assert body["detail"] == "Заявка не найдена"
    assert body["instance"] == f"/api/v2/orders/{order_id}"
    assert body["code"] == "ORDER_NOT_FOUND"
    assert body["requestId"] == request_id
    assert body["errors"] == []


async def test_v2_unauthenticated_request_uses_problem_details(api_client):
    request_id = "v2-contract-auth-001"
    response = await api_client.get(
        f"/api/v2/orders/{uuid.uuid4()}",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 401, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "AUTHENTICATION_REQUIRED"
    assert body["requestId"] == request_id
    assert body["status"] == 401


async def test_v2_invalid_uuid_uses_problem_details(api_client, session_factory):
    await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    response = await api_client.get("/api/v2/orders/not-a-uuid")

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_v2_session_returns_provisional_user_scope(api_client, session_factory):
    user = await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    response = await api_client.get(
        "/api/v2/session", headers={"X-Request-ID": "v2-session-001"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["requestId"] == "v2-session-001"
    assert body["data"]["user"]["id"] == str(user.id)
    assert body["data"]["user"]["displayCurrency"] == "BYN"
    assert body["data"]["commercialScope"] == "USER"
    assert body["data"]["organizationId"] is None
    assert body["data"]["memberships"] == []


async def test_v2_catalog_list_uses_cursor_and_personalized_money(
    api_client, session_factory
):
    brand = await create_brand(session_factory, name="V2 Catalog Brand")
    first = await create_product(
        session_factory,
        sku="V2-CAT-1",
        name="Catalog Alpha",
        brand=brand,
        base_price=100,
        attributes={"model": "Щит распределительный"},
    )
    await create_product(
        session_factory,
        sku="V2-CAT-2",
        name="Catalog Beta",
        brand=brand,
        base_price=200,
    )
    user = await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await set_discount(session_factory, user=user, brand=brand, percent=10)
    await _login(api_client)

    first_page = await api_client.get(
        "/api/v2/catalog/products",
        params={"sort": "sku", "limit": 1},
    )
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert len(first_body["data"]) == 1
    assert first_body["data"][0]["id"] == str(first.id)
    assert first_body["data"][0]["basePrice"] == {
        "amount": "100.00",
        "currency": "BYN",
    }
    assert first_body["data"][0]["clientPrice"] == {
        "amount": "90.00",
        "currency": "BYN",
    }
    assert first_body["data"][0]["exchangeRate"] == {
        "value": "1.0000",
        "scale": 4,
        "source": "BYN",
    }
    assert first_body["meta"]["hasMore"] is True
    assert first_body["meta"]["nextCursor"]

    second_page = await api_client.get(
        "/api/v2/catalog/products",
        params={
            "sort": "sku",
            "limit": 1,
            "cursor": first_body["meta"]["nextCursor"],
        },
    )
    assert second_page.status_code == 200, second_page.text
    second_body = second_page.json()
    assert second_body["data"][0]["sku"] == "V2-CAT-2"
    assert second_body["meta"]["hasMore"] is False
    assert second_body["meta"]["nextCursor"] is None


async def test_v2_catalog_product_by_uuid_and_sku_are_read_only(
    api_client, session_factory
):
    product = await create_product(
        session_factory,
        sku="V2-DETAIL-1",
        name="Detail Product",
        base_price="55.50",
    )
    await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    by_id = await api_client.get(f"/api/v2/catalog/products/{product.id}")
    by_sku = await api_client.get("/api/v2/catalog/products/by-sku/V2-DETAIL-1")
    assert by_id.status_code == 200, by_id.text
    assert by_sku.status_code == 200, by_sku.text
    assert by_id.json()["data"] == by_sku.json()["data"]
    assert by_id.json()["data"]["basePrice"] == {
        "amount": "55.50",
        "currency": "BYN",
    }

    missing = await api_client.get(f"/api/v2/catalog/products/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_v2_catalog_facets_are_authenticated_and_user_scoped(
    api_client, session_factory
):
    brand = await create_brand(session_factory, name="V2 Facet Brand")
    await create_product(
        session_factory,
        sku="V2-FACET-1",
        name="Facet Product",
        brand=brand,
        base_price=10,
        attributes={"model": "Аксессуары"},
    )
    await create_user(
        session_factory,
        email=CLIENT_EMAIL,
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client)

    response = await api_client.get("/api/v2/catalog/facets")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["brands"] == [{"id": str(brand.id), "name": "V2 Facet Brand"}]
    assert data["models"] == ["Аксессуары"]
    assert data["stockStatuses"] == ["IN_STOCK"]
