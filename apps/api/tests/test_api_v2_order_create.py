"""Vertical-slice tests for authenticated API v2 order creation."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.catalog import Product
from app.models.enums import OrganizationRole, StockStatus, UserRole
from app.models.order import Order
from app.models.organization import OrganizationAddress
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_series,
    create_user,
    set_active_organization,
    set_discount,
    set_fixed_rate_for_user,
    set_organization_brand_term,
    set_organization_pricing_agreement,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "v2-create-client@example.by"
MANAGER_EMAIL = "v2-create-manager@example.by"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def _payload(*products, quantity: str = "3", note: str | None = None, address_id: str | None = None) -> dict:
    delivery: dict = {
        "method": "DELIVERY",
        "contactName": "Иван",
        "phone": "+375291234567",
        "preferredDate": "2026-10-02",
        "comment": "После 14:00",
    }
    # addressId задаёт только тест снапшота адреса: DELIVERY без него валиден.
    if address_id is not None:
        delivery["addressId"] = address_id
    return {
        "draftId": None,
        "items": [
            {
                "productId": str(product.id if hasattr(product, "id") else product),
                "quantity": quantity,
                "note": note,
            }
            for product in products
        ],
        "delivery": delivery,
    }


async def _order_count(session_factory) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count(Order.id))) or 0)


async def test_create_order_by_product_id_uses_org_scope_and_delivery_snapshot(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name="Create Org")
    await add_organization_membership(
        session_factory,
        user=user,
        organization=organization,
        role=OrganizationRole.OWNER,
        is_primary=True,
    )
    await set_active_organization(session_factory, user=user, organization=organization)
    brand = await create_brand(session_factory, name="Create Brand")
    series = await create_series(
        session_factory,
        brand=brand,
        name="Create Series",
        photo_key="photos-series/internal-series-key.webp",
    )
    product = await create_product(
        session_factory,
        sku="V2-CREATE-1",
        name="Createable product",
        brand=brand,
        series=series,
        base_price=100,
        stock_qty=10,
    )
    await set_organization_brand_term(
        session_factory,
        organization=organization,
        brand=brand,
        percent=20,
    )
    await set_discount(session_factory, user=user, brand=brand, percent=90)
    org_rate = await set_rate(
        session_factory, currency="USD", rate=2, scale=1, source="ORG_FIXTURE"
    )
    await set_organization_pricing_agreement(
        session_factory,
        organization=organization,
        display_currency="USD",
        fixed_rate_id=org_rate.id,
        agreement_reference="ORG-AGREEMENT-1",
    )
    legacy_rate = await set_rate(
        session_factory, currency="USD", rate=4, scale=1, source="LEGACY_FIXTURE"
    )
    await set_fixed_rate_for_user(session_factory, user=user, rate=legacy_rate)
    async with session_factory() as session:
        address = OrganizationAddress(
            organization_id=organization.id,
            kind="DELIVERY",
            label="Склад",
            address_line="ул. Тестовая, 1",
            city="Минск",
            postal_code="220000",
            is_default=True,
        )
        session.add(address)
        await session.commit()
        address_id = str(address.id)
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.post(
        "/api/v2/orders",
        json=_payload(product, note="Отдельной строкой", address_id=address_id),
        headers={
            "Idempotency-Key": "v2-create-success-001",
            "X-Request-ID": "v2-create-request-001",
        },
    )

    assert response.status_code == 201, response.text
    assert response.headers["X-Idempotency-Replayed"] == "false"
    body = response.json()
    assert body["meta"]["requestId"] == "v2-create-request-001"
    order = body["data"]
    assert order["status"] == "NEW"
    assert order["organizationId"] == str(organization.id)
    assert order["initiatedByUserId"] == str(user.id)
    assert order["total"] == {"amount": "120.00", "currency": "USD"}
    assert order["exchangeRate"] == {
        "value": "2.0000",
        "scale": 4,
        "source": "FIXED",
    }
    assert order["lines"] == [
        {
            "id": order["lines"][0]["id"],
            "productId": str(product.id),
            "sku": "V2-CREATE-1",
            "name": "Createable product",
            "quantity": 3,
            "unitPrice": {"amount": "40.00", "currency": "USD"},
            "lineTotal": {"amount": "120.00", "currency": "USD"},
            "note": "Отдельной строкой",
        }
    ]
    assert order["delivery"] == {
        "method": "DELIVERY",
        "pickupPoint": None,
        "addressId": address_id,
        "address": "ул. Тестовая, 1, Минск, 220000",
        "contactName": "Иван",
        "phone": "+375291234567",
        "preferredDate": "2026-10-02",
        "comment": "После 14:00",
    }
    assert "photoKey" not in response.text
    assert "photos-series/internal-series-key.webp" not in response.text
    assert "s3" not in response.text.lower()

    async with session_factory() as session:
        stored = await session.get(Product, product.id)
        assert stored.stock_qty == 10


async def test_duplicate_product_id_is_a_validation_error_without_merge(
    api_client, session_factory
):
    await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Duplicate Brand")
    product = await create_product(
        session_factory,
        sku="V2-DUP-1",
        name="Duplicate product",
        brand=brand,
        base_price=10,
        stock_qty=10,
    )
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.post(
        "/api/v2/orders",
        json=_payload(product, product, quantity="2"),
        headers={"Idempotency-Key": "v2-create-duplicate-001"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == "VALIDATION_ERROR"
    assert any(error["code"] == "DUPLICATE_ORDER_LINES" for error in problem["errors"])
    assert await _order_count(session_factory) == 0


async def test_unknown_archived_and_exceeded_stock_use_stable_problem_codes(
    api_client, session_factory
):
    await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Failure Brand")
    archived = await create_product(
        session_factory,
        sku="V2-ARCHIVED-1",
        name="Archived product",
        brand=brand,
        base_price=10,
        stock=StockStatus.ARCHIVED,
    )
    limited = await create_product(
        session_factory,
        sku="V2-LIMITED-1",
        name="Limited product",
        brand=brand,
        base_price=10,
        stock_qty=5,
    )
    await _login(api_client, CLIENT_EMAIL)

    unknown = await api_client.post(
        "/api/v2/orders",
        json=_payload(uuid.uuid4(), quantity="1"),
        headers={"Idempotency-Key": "v2-create-unknown-001"},
    )
    unavailable = await api_client.post(
        "/api/v2/orders",
        json=_payload(archived, quantity="1"),
        headers={"Idempotency-Key": "v2-create-archived-001"},
    )
    insufficient = await api_client.post(
        "/api/v2/orders",
        json=_payload(limited, quantity="6"),
        headers={"Idempotency-Key": "v2-create-stock-001"},
    )

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "PRODUCT_NOT_FOUND"
    assert unavailable.status_code == 400
    assert unavailable.json()["code"] == "PRODUCT_UNAVAILABLE"
    assert insufficient.status_code == 409
    assert insufficient.json()["code"] == "INSUFFICIENT_STOCK"
    assert await _order_count(session_factory) == 0
    async with session_factory() as session:
        assert (await session.get(Product, limited.id)).stock_qty == 5


async def test_idempotent_replay_rejects_changed_payload_and_changed_org_scope(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Idempotency Brand")
    first_product = await create_product(
        session_factory,
        sku="V2-IDEMP-1",
        name="First product",
        brand=brand,
        base_price=10,
        stock_qty=20,
    )
    second_product = await create_product(
        session_factory,
        sku="V2-IDEMP-2",
        name="Second product",
        brand=brand,
        base_price=20,
        stock_qty=20,
    )
    first_org = await create_organization(session_factory, legal_name="First Org")
    second_org = await create_organization(session_factory, legal_name="Second Org")
    for organization in (first_org, second_org):
        await add_organization_membership(
            session_factory,
            user=user,
            organization=organization,
            role=OrganizationRole.BUYER,
        )
    await set_active_organization(session_factory, user=user, organization=first_org)
    await _login(api_client, CLIENT_EMAIL)
    payload = _payload(first_product, second_product, quantity="2")
    key = {"Idempotency-Key": "v2-create-replay-001"}

    created = await api_client.post("/api/v2/orders", json=payload, headers=key)
    replay_payload = _payload(second_product, first_product, quantity="2")
    replayed = await api_client.post(
        "/api/v2/orders", json=replay_payload, headers=key
    )
    changed = await api_client.post(
        "/api/v2/orders",
        json=_payload(first_product, second_product, quantity="3"),
        headers=key,
    )

    assert created.status_code == replayed.status_code == 201
    assert created.headers["X-Idempotency-Replayed"] == "false"
    assert replayed.headers["X-Idempotency-Replayed"] == "true"
    assert replayed.json()["data"]["id"] == created.json()["data"]["id"]
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _order_count(session_factory) == 1

    await set_active_organization(session_factory, user=user, organization=second_org)
    changed_scope = await api_client.post(
        "/api/v2/orders", json=payload, headers=key
    )
    assert changed_scope.status_code == 409
    assert changed_scope.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _order_count(session_factory) == 1


async def test_idempotency_key_is_required_and_malformed_values_are_rejected(
    api_client, session_factory
):
    await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Header Brand")
    product = await create_product(
        session_factory,
        sku="V2-HEADER-1",
        name="Header product",
        brand=brand,
        base_price=10,
    )
    await _login(api_client, CLIENT_EMAIL)
    payload = _payload(product, quantity="1")

    missing = await api_client.post("/api/v2/orders", json=payload)
    malformed = await api_client.post(
        "/api/v2/orders",
        json=payload,
        headers={"Idempotency-Key": "x" * 256},
    )

    assert missing.status_code == 422
    assert missing.json()["code"] == "VALIDATION_ERROR"
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "VALIDATION_ERROR"
    assert malformed.json()["errors"][0]["field"] == "Idempotency-Key"
    assert await _order_count(session_factory) == 0


async def test_create_order_requires_authentication_and_client_role(
    api_client, session_factory
):
    brand = await create_brand(session_factory, name="Role Brand")
    product = await create_product(
        session_factory,
        sku="V2-ROLE-1",
        name="Role product",
        brand=brand,
        base_price=10,
    )
    payload = _payload(product, quantity="1")
    headers = {"Idempotency-Key": "v2-create-anonymous-001"}

    anonymous = await api_client.post(
        "/api/v2/orders", json=payload, headers=headers
    )
    await create_user(
        session_factory,
        email=MANAGER_EMAIL,
        role=UserRole.MANAGER,
        password=PASSWORD,
    )
    await _login(api_client, MANAGER_EMAIL)
    manager = await api_client.post(
        "/api/v2/orders",
        json=payload,
        headers={"Idempotency-Key": "v2-create-manager-001"},
    )

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert manager.status_code == 403
    assert manager.json()["code"] == "PERMISSION_DENIED"
    assert await _order_count(session_factory) == 0
