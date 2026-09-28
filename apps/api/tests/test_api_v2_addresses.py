"""Vertical-slice tests for the API v2 organization address book (Этап 2)."""
from __future__ import annotations

import uuid

from app.models.enums import OrganizationRole, UserRole
from tests.conftest import (
    add_organization_membership,
    create_brand,
    create_organization,
    create_product,
    create_user,
    set_active_organization,
)

PASSWORD = "Passw0rd!"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


_ADDRESS_BODY = {
    "kind": "DELIVERY",
    "label": "Склад",
    "recipientName": "Иван Иванов",
    "phone": "+375291234567",
    "addressLine": "ул. Тестовая, 1",
    "city": "Минск",
    "postalCode": "220000",
    "countryCode": "BY",
    "isDefault": True,
}


def _address_body(**overrides) -> dict:
    body = {**_ADDRESS_BODY, **overrides}
    return body


async def _member_user(
    session_factory,
    *,
    email: str,
    organization,
    role: OrganizationRole,
    activate: bool = True,
):
    user = await create_user(
        session_factory, email=email, role=UserRole.CLIENT, password=PASSWORD
    )
    await add_organization_membership(
        session_factory, user=user, organization=organization, role=role
    )
    if activate:
        await set_active_organization(
            session_factory, user=user, organization=organization
        )
    return user


async def test_address_book_crud_cycle(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Addr Org")
    await _member_user(
        session_factory,
        email="addr-owner@example.by",
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _login(api_client, "addr-owner@example.by")

    created = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(),
        headers={"Idempotency-Key": "addr-create-001"},
    )
    assert created.status_code == 201, created.text
    address = created.json()["data"]
    assert address["kind"] == "DELIVERY"
    assert address["addressLine"] == "ул. Тестовая, 1"
    assert address["recipientName"] == "Иван Иванов"
    assert address["isDefault"] is True
    assert "address_line" not in created.text

    listed = await api_client.get("/api/v2/me/organization/addresses")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [address["id"]]

    patched = await api_client.patch(
        f"/api/v2/me/organization/addresses/{address['id']}",
        json={"label": "Основной склад", "city": "Гомель"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["label"] == "Основной склад"
    assert patched.json()["data"]["city"] == "Гомель"
    assert patched.json()["data"]["addressLine"] == "ул. Тестовая, 1"

    deleted = await api_client.delete(
        f"/api/v2/me/organization/addresses/{address['id']}"
    )
    assert deleted.status_code == 204
    emptied = await api_client.get("/api/v2/me/organization/addresses")
    assert emptied.json()["data"] == []


async def test_post_is_idempotent_by_natural_key(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Idem Org")
    await _member_user(
        session_factory,
        email="addr-idem@example.by",
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    await _login(api_client, "addr-idem@example.by")
    headers = {"Idempotency-Key": "addr-idem-001"}

    first = await api_client.post(
        "/api/v2/me/organization/addresses", json=_address_body(), headers=headers
    )
    replay = await api_client.post(
        "/api/v2/me/organization/addresses", json=_address_body(), headers=headers
    )
    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert first.json()["data"]["id"] == replay.json()["data"]["id"]

    listed = await api_client.get("/api/v2/me/organization/addresses")
    assert len(listed.json()["data"]) == 1

    other = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(addressLine="ул. Другая, 2"),
        headers=headers,
    )
    assert other.status_code == 201
    assert other.json()["data"]["id"] != first.json()["data"]["id"]


async def test_default_flag_is_unique_per_kind(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Def Org")
    await _member_user(
        session_factory,
        email="addr-def@example.by",
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _login(api_client, "addr-def@example.by")

    first = (
        await api_client.post(
            "/api/v2/me/organization/addresses",
            json=_address_body(addressLine="ул. Первая, 1", isDefault=True),
            headers={"Idempotency-Key": "addr-def-1"},
        )
    ).json()["data"]
    second = (
        await api_client.post(
            "/api/v2/me/organization/addresses",
            json=_address_body(addressLine="ул. Вторая, 2", isDefault=True),
            headers={"Idempotency-Key": "addr-def-2"},
        )
    ).json()["data"]
    pickup = (
        await api_client.post(
            "/api/v2/me/organization/addresses",
            json=_address_body(kind="PICKUP", addressLine="ул. Третья, 3", isDefault=True),
            headers={"Idempotency-Key": "addr-def-3"},
        )
    ).json()["data"]

    listed = {
        item["id"]: item
        for item in (
            await api_client.get("/api/v2/me/organization/addresses")
        ).json()["data"]
    }
    assert listed[first["id"]]["isDefault"] is False
    assert listed[second["id"]]["isDefault"] is True
    # PICKUP — другой kind: его default живёт независимо.
    assert listed[pickup["id"]]["isDefault"] is True

    back = await api_client.patch(
        f"/api/v2/me/organization/addresses/{first['id']}", json={"isDefault": True}
    )
    assert back.status_code == 200
    listed = {
        item["id"]: item
        for item in (
            await api_client.get("/api/v2/me/organization/addresses")
        ).json()["data"]
    }
    assert listed[first["id"]]["isDefault"] is True
    assert listed[second["id"]]["isDefault"] is False
    assert listed[pickup["id"]]["isDefault"] is True


async def test_contact_reads_but_cannot_write(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Role Org")
    await _member_user(
        session_factory,
        email="addr-writer@example.by",
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _member_user(
        session_factory,
        email="addr-contact@example.by",
        organization=organization,
        role=OrganizationRole.CONTACT,
    )
    await _login(api_client, "addr-contact@example.by")

    forbidden = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(),
        headers={"Idempotency-Key": "addr-role-001"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ADDRESS_FORBIDDEN"

    listed = await api_client.get("/api/v2/me/organization/addresses")
    assert listed.status_code == 200
    assert listed.json()["data"] == []


async def test_foreign_address_is_404(api_client, session_factory):
    first_org = await create_organization(session_factory, legal_name="Org One")
    second_org = await create_organization(session_factory, legal_name="Org Two")
    owner_one = await _member_user(
        session_factory,
        email="addr-one@example.by",
        organization=first_org,
        role=OrganizationRole.OWNER,
    )
    await _member_user(
        session_factory,
        email="addr-two@example.by",
        organization=second_org,
        role=OrganizationRole.OWNER,
    )
    await _login(api_client, "addr-one@example.by")
    created = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(),
        headers={"Idempotency-Key": "addr-foreign-001"},
    )
    address_id = created.json()["data"]["id"]

    await _login(api_client, "addr-two@example.by")
    foreign_patch = await api_client.patch(
        f"/api/v2/me/organization/addresses/{address_id}", json={"city": "Брест"}
    )
    foreign_delete = await api_client.delete(
        f"/api/v2/me/organization/addresses/{address_id}"
    )
    unknown_get_list = await api_client.get("/api/v2/me/organization/addresses")
    assert foreign_patch.status_code == 404
    assert foreign_patch.json()["code"] == "ADDRESS_NOT_FOUND"
    assert foreign_delete.status_code == 404
    assert unknown_get_list.json()["data"] == []
    assert owner_one is not None


async def test_solo_client_has_no_address_book(api_client, session_factory):
    await create_user(
        session_factory,
        email="addr-solo@example.by",
        role=UserRole.CLIENT,
        password=PASSWORD,
    )
    await _login(api_client, "addr-solo@example.by")

    listed = await api_client.get("/api/v2/me/organization/addresses")
    assert listed.status_code == 200
    assert listed.json()["data"] == []

    rejected = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(),
        headers={"Idempotency-Key": "addr-solo-001"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "NO_ORGANIZATION"


async def test_post_requires_idempotency_key(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Key Org")
    await _member_user(
        session_factory,
        email="addr-key@example.by",
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    await _login(api_client, "addr-key@example.by")

    missing = await api_client.post(
        "/api/v2/me/organization/addresses", json=_address_body()
    )
    malformed = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(addressLine="ул. Ключевая, 4"),
        headers={"Idempotency-Key": "bad key\n"},
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "VALIDATION_ERROR"
    assert malformed.status_code == 422


async def test_patch_null_clears_optional_but_not_required(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Null Org")
    await _member_user(
        session_factory,
        email="addr-null@example.by",
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    await _login(api_client, "addr-null@example.by")
    created = await api_client.post(
        "/api/v2/me/organization/addresses",
        json=_address_body(),
        headers={"Idempotency-Key": "addr-null-001"},
    )
    address_id = created.json()["data"]["id"]

    cleared = await api_client.patch(
        f"/api/v2/me/organization/addresses/{address_id}",
        json={"city": None, "phone": None, "label": None},
    )
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()["data"]
    assert body["city"] is None and body["phone"] is None and body["label"] is None
    # absent — прежнее значение сохраняется.
    assert body["recipientName"] == "Иван Иванов"

    null_kind = await api_client.patch(
        f"/api/v2/me/organization/addresses/{address_id}", json={"kind": None}
    )
    assert null_kind.status_code == 422
    assert null_kind.json()["code"] == "VALIDATION_ERROR"


async def test_order_rejects_foreign_delivery_address(api_client, session_factory):
    own_org = await create_organization(session_factory, legal_name="Own Org")
    foreign_org = await create_organization(session_factory, legal_name="Foreign Org")
    await _member_user(
        session_factory,
        email="addr-own@example.by",
        organization=own_org,
        role=OrganizationRole.OWNER,
    )
    foreign_owner = await _member_user(
        session_factory,
        email="addr-fgn@example.by",
        organization=foreign_org,
        role=OrganizationRole.OWNER,
    )
    brand = await create_brand(session_factory, name="Addr Brand")
    product = await create_product(
        session_factory,
        sku="V2-ADDR-1",
        name="Address product",
        brand=brand,
        base_price=10,
        stock_qty=20,
    )
    # Адрес создаётся сессией напрямую: он принадлежит ЧУЖОЙ организации.
    from app.models.organization import OrganizationAddress

    async with session_factory() as session:
        foreign_address = OrganizationAddress(
            organization_id=foreign_org.id,
            kind="DELIVERY",
            address_line="ул. Чужая, 9",
        )
        session.add(foreign_address)
        await session.commit()
        foreign_address_id = str(foreign_address.id)

    await _login(api_client, "addr-own@example.by")
    response = await api_client.post(
        "/api/v2/orders",
        json={
            "draftId": None,
            "items": [
                {"productId": str(product.id), "quantity": "1", "note": None}
            ],
            "delivery": {
                "method": "DELIVERY",
                "addressId": foreign_address_id,
            },
        },
        headers={"Idempotency-Key": f"addr-order-{uuid.uuid4()}"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "ADDRESS_NOT_FOUND"
    assert foreign_owner is not None
