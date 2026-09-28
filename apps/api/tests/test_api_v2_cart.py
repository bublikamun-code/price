"""API v2 organization-aware cart contract tests."""
from __future__ import annotations

import uuid

from app.models.enums import OrganizationRole, StockStatus, UserRole
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
    set_organization_brand_term,
    set_organization_pricing_agreement,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "v2-cart-client@example.by"
MANAGER_EMAIL = "v2-cart-manager@example.by"


async def _login(api_client, email: str = CLIENT_EMAIL) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _seed_client_product(session_factory, *, sku: str = "V2-CART-1"):
    user = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="V2 Cart Brand")
    product = await create_product(
        session_factory,
        sku=sku,
        name="V2 Cart Product",
        brand=brand,
        base_price=100,
        stock_qty=100,
    )
    return user, brand, product


async def _set_organization_scope(
    session_factory,
    *,
    user,
    organization,
    brand,
    currency: str = "USD",
    rate_value: str = "2",
    discount_percent: int = 20,
):
    await add_organization_membership(
        session_factory,
        user=user,
        organization=organization,
        role=OrganizationRole.BUYER,
        is_primary=True,
    )
    await set_active_organization(session_factory, user=user, organization=organization)
    await set_organization_brand_term(
        session_factory,
        organization=organization,
        brand=brand,
        percent=discount_percent,
    )
    rate = await set_rate(
        session_factory,
        currency=currency,
        rate=rate_value,
        scale=1,
        source="ORG_FIXTURE",
    )
    await set_organization_pricing_agreement(
        session_factory,
        organization=organization,
        display_currency=currency,
        fixed_rate_id=rate.id,
        agreement_reference="V2-CART-AGREEMENT",
    )


async def test_empty_user_cart_is_versioned_and_authenticated(api_client, session_factory):
    user, _, _ = await _seed_client_product(session_factory)

    anonymous = await api_client.get("/api/v2/cart")
    await _login(api_client)
    response = await api_client.get("/api/v2/cart")

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"1"'
    body = response.json()
    assert body["meta"]["requestId"]
    assert body["data"]["organizationId"] is None
    assert body["data"]["version"] == 1
    assert body["data"]["items"] == []
    assert body["data"]["totalItems"] == 0
    assert body["data"]["total"] == {"amount": "0.00", "currency": "BYN"}
    assert body["data"]["exchangeRate"] == {
        "value": "1.0000",
        "scale": 4,
        "source": "BYN",
    }
    assert "photoKey" not in response.text
    assert "photo_key" not in response.text
    assert user.id


async def test_manager_cannot_read_or_mutate_client_cart(api_client, session_factory):
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.get("/api/v2/cart")
    mutation = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(uuid.uuid4()), "quantity": "1"},
        headers={"If-Match": "1"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
    assert mutation.status_code == 403
    assert mutation.json()["code"] == "PERMISSION_DENIED"


async def test_add_accumulates_put_replaces_and_delete_clear_advance_etag(
    api_client, session_factory
):
    _, _, product = await _seed_client_product(session_factory)
    await _login(api_client)

    first = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "2", "note": "первая"},
        headers={"If-Match": "1"},
    )
    assert first.status_code == 200, first.text
    assert first.headers["etag"] == '"2"'
    assert first.json()["data"]["items"][0]["quantity"] == 2
    assert first.json()["data"]["items"][0]["note"] == "первая"

    second = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "3", "note": None},
        headers={"If-Match": "2"},
    )
    assert second.status_code == 200, second.text
    assert second.headers["etag"] == '"3"'
    assert second.json()["data"]["items"][0]["quantity"] == 5
    assert second.json()["data"]["items"][0]["note"] == "первая"

    replaced = await api_client.put(
        f"/api/v2/cart/items/{product.id}",
        json={"quantity": "7", "note": None},
        headers={"If-Match": "3"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.headers["etag"] == '"4"'
    assert replaced.json()["data"]["items"][0]["quantity"] == 7
    assert replaced.json()["data"]["items"][0]["note"] is None
    assert replaced.json()["data"]["total"] == {
        "amount": "700.00",
        "currency": "BYN",
    }

    deleted = await api_client.delete(
        f"/api/v2/cart/items/{product.id}", headers={"If-Match": "4"}
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.headers["etag"] == '"5"'
    assert deleted.json()["data"]["items"] == []

    cleared = await api_client.delete("/api/v2/cart", headers={"If-Match": "5"})
    assert cleared.status_code == 200, cleared.text
    assert cleared.headers["etag"] == '"6"'
    assert cleared.json()["data"]["items"] == []


async def test_stale_retry_and_invalid_if_match_do_not_duplicate_quantity(
    api_client, session_factory
):
    _, _, product = await _seed_client_product(session_factory)
    await _login(api_client)

    first = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "2"},
        headers={"If-Match": "1"},
    )
    retry = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "2"},
        headers={"If-Match": "1"},
    )
    malformed = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "1"},
        headers={"If-Match": '"01"'},
    )
    missing = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "1"},
    )

    assert first.status_code == 200
    assert retry.status_code == 409
    assert retry.json()["code"] == "STALE_RESOURCE_VERSION"
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "INVALID_IF_MATCH"
    assert missing.status_code == 400
    assert missing.json()["code"] == "INVALID_IF_MATCH"

    current = await api_client.get("/api/v2/cart")
    assert current.status_code == 200
    assert current.json()["data"]["version"] == 2
    assert current.json()["data"]["items"][0]["quantity"] == 2


async def test_quantity_contract_rejects_non_canonical_values_without_mutation(
    api_client, session_factory
):
    _, _, product = await _seed_client_product(session_factory)
    await _login(api_client)

    for quantity in (1, "0", "01", "-1", "2147483648", ""):
        response = await api_client.post(
            "/api/v2/cart/items",
            json={"productId": str(product.id), "quantity": quantity},
            headers={"If-Match": "1"},
        )
        assert response.status_code == 422, (quantity, response.text)
        assert response.json()["code"] == "VALIDATION_ERROR"

    current = await api_client.get("/api/v2/cart")
    assert current.json()["data"]["version"] == 1
    assert current.json()["data"]["items"] == []


async def test_unknown_and_archived_products_use_stable_problem_codes(
    api_client, session_factory
):
    _, brand, product = await _seed_client_product(session_factory)
    archived = await create_product(
        session_factory,
        sku="V2-CART-ARCHIVED",
        name="Archived",
        brand=brand,
        stock=StockStatus.ARCHIVED,
    )
    await _login(api_client)

    unknown = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(uuid.uuid4()), "quantity": "1"},
        headers={"If-Match": "1"},
    )
    unavailable = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(archived.id), "quantity": "1"},
        headers={"If-Match": "1"},
    )

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "PRODUCT_NOT_FOUND"
    assert unavailable.status_code == 400
    assert unavailable.json()["code"] == "PRODUCT_UNAVAILABLE"
    assert (await api_client.get("/api/v2/cart")).json()["data"]["version"] == 1
    assert product.id


async def test_organization_cart_is_separate_and_uses_organization_pricing(
    api_client, session_factory
):
    user, brand, product = await _seed_client_product(session_factory)
    first_org = await create_organization(session_factory, legal_name="Cart Org One")
    second_org = await create_organization(session_factory, legal_name="Cart Org Two")
    await _set_organization_scope(
        session_factory,
        user=user,
        organization=first_org,
        brand=brand,
    )
    await add_organization_membership(
        session_factory,
        user=user,
        organization=second_org,
        role=OrganizationRole.BUYER,
    )
    await _login(api_client)

    first = await api_client.get("/api/v2/cart")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["organizationId"] == str(first_org.id)
    assert first.json()["data"]["exchangeRate"]["source"] == "FIXED"
    assert first.json()["data"]["exchangeRate"]["value"] == "2.0000"

    first_add = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "1"},
        headers={"If-Match": "1"},
    )
    assert first_add.status_code == 200, first_add.text
    assert first_add.json()["data"]["items"][0]["unitPrice"] == {
        "amount": "40.00",
        "currency": "USD",
    }
    first_cart_id = first_add.json()["data"]["id"]

    await set_active_organization(session_factory, user=user, organization=second_org)
    second = await api_client.get("/api/v2/cart")
    assert second.status_code == 200, second.text
    assert second.json()["data"]["organizationId"] == str(second_org.id)
    assert second.json()["data"]["items"] == []
    assert second.json()["data"]["exchangeRate"]["source"] == "BYN"
    second_add = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "1"},
        headers={"If-Match": "1"},
    )
    assert second_add.status_code == 200, second_add.text
    assert second_add.json()["data"]["id"] != first_cart_id
    assert second_add.json()["data"]["items"][0]["unitPrice"] == {
        "amount": "100.00",
        "currency": "BYN",
    }


async def test_organization_cart_repeat_mismatch_and_create_scope_isolation(
    api_client, session_factory
):
    user, brand, product = await _seed_client_product(session_factory)
    order_org = await create_organization(session_factory, legal_name="Repeat Org")
    other_org = await create_organization(session_factory, legal_name="Other Org")
    await _set_organization_scope(
        session_factory, user=user, organization=order_org, brand=brand
    )
    await add_organization_membership(
        session_factory, user=user, organization=other_org, role=OrganizationRole.BUYER
    )
    await _login(api_client)
    await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": "1"},
        headers={"If-Match": "1"},
    )
    await create_product(
        session_factory,
        sku="V2-REPEAT-CART-1",
        name="Repeat source",
        brand=brand,
        base_price=10,
    )
    order = await api_client.post(
        "/api/v2/orders",
        json={
            "items": [
                {"productId": str(product.id), "quantity": "1", "note": None}
            ],
            "delivery": {
                # Без addressId: тест про scope корзины, а с этапа 2 адресной
                # книги несуществующий addressId — это 404 ADDRESS_NOT_FOUND.
                "method": "DELIVERY",
                "contactName": "Иван",
                "phone": "+375291234567",
                "preferredDate": "2026-10-02",
                "comment": None,
            },
        },
        headers={"Idempotency-Key": "v2-cart-order-001"},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["data"]["id"]
    cleared = await api_client.get("/api/v2/cart")
    assert cleared.status_code == 200, cleared.text
    assert cleared.headers["etag"] == '"3"'
    assert cleared.json()["data"]["organizationId"] == str(order_org.id)
    assert cleared.json()["data"]["items"] == []

    await set_active_organization(session_factory, user=user, organization=other_org)
    mismatch = await api_client.post(
        f"/api/v2/orders/{order_id}/repeat", headers={"If-Match": "1"}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "CART_SCOPE_MISMATCH"
