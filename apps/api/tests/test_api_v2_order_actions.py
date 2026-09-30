"""Focused contract tests for API v2 client order actions."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.enums import OrganizationRole, OrderStatus, UserRole
from app.models.order import Order, OrderItem
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
)

PASSWORD = "Passw0rd!"
EMAIL = "v2-actions-client@example.by"
OUTSIDER_EMAIL = "v2-actions-outsider@example.by"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _seed_order(
    session_factory,
    *,
    client,
    product,
    organization_id=None,
    status: OrderStatus = OrderStatus.NEW,
) -> Order:
    async with session_factory() as session:
        order = Order(
            client_id=client.id,
            organization_id=organization_id,
            status=status,
            currency_code="BYN",
            exchange_rate="1.0000",
            rate_source="BYN",
            total_amount="40.00",
            delivery_method="pickup",
            delivery_point="Минск",
            created_at=datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc),
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_snapshot={"sku": product.sku, "name": product.name},
                quantity=4,
                unit_price="10.00",
                currency_code="BYN",
                note="Повторить строку",
            )
        )
        await session.commit()
        await session.refresh(order)
        return order


async def test_cancel_order_returns_v2_detail_and_problem_for_completed(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Action Brand")
    product = await create_product(
        session_factory, sku="V2-ACTION-1", name="Action product", brand=brand, base_price=10
    )
    order = await _seed_order(session_factory, client=user, product=product)
    await _login(api_client, EMAIL)

    response = await api_client.post(
        f"/api/v2/orders/{order.id}/cancel",
        headers={"X-Request-ID": "v2-cancel-001"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["requestId"] == "v2-cancel-001"
    assert body["data"]["status"] == "CANCELLED"
    assert body["data"]["lines"][0]["quantity"] == 4
    assert "photoKey" not in response.text
    assert "s3" not in response.text.lower()

    async with session_factory() as session:
        stored = await session.get(Order, order.id)
        stored.status = OrderStatus.COMPLETED
        await session.commit()

    conflict = await api_client.post(f"/api/v2/orders/{order.id}/cancel")
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")
    assert conflict.json()["code"] == "ORDER_NOT_CANCELABLE"


async def test_repeat_order_returns_safe_v2_cart_projection(
    api_client, session_factory
):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    brand = await create_brand(session_factory, name="Repeat Brand")
    product = await create_product(
        session_factory,
        sku="V2-REPEAT-1",
        name="Repeat product",
        brand=brand,
        base_price=10,
    )
    order = await _seed_order(session_factory, client=user, product=product)
    await _login(api_client, EMAIL)

    response = await api_client.post(
        f"/api/v2/orders/{order.id}/repeat",
        headers={
            "X-Request-ID": "v2-repeat-001",
            "If-Match": "1",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["requestId"] == "v2-repeat-001"
    assert body["data"]["totalItems"] == 1
    assert body["data"]["total"] == {"amount": "40.00", "currency": "BYN"}
    assert body["data"]["items"][0] == {
        "productId": str(product.id),
        "sku": "V2-REPEAT-1",
        "name": "Repeat product",
        "brandName": "Repeat Brand",
        "stockStatus": "IN_STOCK",
        "quantity": 4,
        "note": "Повторить строку",
        "unitPrice": {"amount": "10.00", "currency": "BYN"},
        "lineTotal": {"amount": "40.00", "currency": "BYN"},
        # Ступени скидок за объём не заданы → null (§16 п.41)
        "volumeTier": None,
    }
    assert "photoKey" not in response.text
    assert "photo_key" not in response.text


async def test_order_actions_enforce_organization_membership(
    api_client, session_factory
):
    owner = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    await create_user(
        session_factory, email=OUTSIDER_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    organization = await create_organization(session_factory, legal_name="Action Org")
    await add_organization_membership(
        session_factory,
        user=owner,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    brand = await create_brand(session_factory, name="Org Action Brand")
    product = await create_product(
        session_factory, sku="V2-ORG-ACTION-1", name="Org product", brand=brand, base_price=10
    )
    order = await _seed_order(
        session_factory,
        client=owner,
        product=product,
        organization_id=organization.id,
    )
    await set_active_organization(
        session_factory, user=owner, organization=organization
    )

    await _login(api_client, OUTSIDER_EMAIL)
    cancel = await api_client.post(f"/api/v2/orders/{order.id}/cancel")
    repeat = await api_client.post(
        f"/api/v2/orders/{order.id}/repeat",
        headers={"If-Match": "1"},
    )
    assert cancel.status_code == 404
    assert cancel.json()["code"] == "ORDER_NOT_FOUND"
    assert repeat.status_code == 404
    assert repeat.json()["code"] == "ORDER_NOT_FOUND"
