"""Кросс-справочник клиентских артикулов: CRUD и права (§16 п.43, этап 7).

Покрывает: CRUD org-скоупа (создание/дубль/список с фильтром/PATCH If-Match/
удаление), права (BUYER пишет, VIEWER/CONTACT только читают, соло-клиент без
организации → 422 ORGANIZATION_REQUIRED), manager-роутер (staff CRUD по чужой
организации, не-staff 403), валидацию товара (404/PRODUCT_ARCHIVED).
"""
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
)

PASSWORD = "Passw0rd!"
OWNER_EMAIL = "csku-owner@example.by"
BUYER_EMAIL = "csku-buyer@example.by"
VIEWER_EMAIL = "csku-viewer@example.by"
CONTACT_EMAIL = "csku-contact@example.by"
SOLO_EMAIL = "csku-solo@example.by"
MANAGER_EMAIL = "csku-manager@example.by"

MAPPINGS_URL = "/api/v2/me/organization/client-sku-mappings"
MANAGER_MAPPINGS_URL = "/api/v2/manager/organizations"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


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


async def _product(session_factory, *, sku: str, name: str, stock=StockStatus.IN_STOCK):
    brand = await create_brand(session_factory, name=f"Brand {sku}")
    return await create_product(
        session_factory, sku=sku, name=name, brand=brand, base_price=100
    )


def _body(product, client_sku: str = "Привод ГТУ-2", note: str | None = None) -> dict:
    return {
        "clientSku": client_sku,
        "productId": str(product.id),
        "note": note,
    }


def _body_uuid_only(*, client_sku: str, product_id: str) -> dict:
    return {"clientSku": client_sku, "productId": product_id, "note": None}


async def test_create_mapping_201_and_list(api_client, session_factory):
    """BUYER создаёт связку → 201; GET отдаёт страницу с meta (§16 п.43 п.6)."""
    organization = await create_organization(session_factory, legal_name="Csku Org")
    await _member_user(
        session_factory,
        email=BUYER_EMAIL,
        organization=organization,
        role=OrganizationRole.BUYER,
    )
    product = await _product(session_factory, sku="VENT-2", name="Привод ГТУ-2")
    await _login(api_client, BUYER_EMAIL)

    created = await api_client.post(
        MAPPINGS_URL,
        json=_body(product, client_sku="  Привод ГТУ-2  ", note="аналог VENT-100"),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["clientSku"] == "Привод ГТУ-2"  # trim на границе
    assert data["productId"] == str(product.id)
    assert data["organizationId"] == str(organization.id)
    assert data["note"] == "аналог VENT-100"
    assert data["version"] == 1
    assert "client_sku" not in created.text

    listed = await api_client.get(MAPPINGS_URL)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert [item["id"] for item in payload["data"]] == [data["id"]]
    assert payload["meta"]["page"] == 1
    assert payload["meta"]["pageSize"] == 20
    assert payload["meta"]["total"] == 1


async def test_duplicate_client_sku_409_case_insensitive(api_client, session_factory):
    """Дубль (org, client_sku) → 409 CLIENT_SKU_MAPPING_EXISTS; регистр не важен (CITEXT)."""
    organization = await create_organization(session_factory, legal_name="Csku Dup Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    product = await _product(session_factory, sku="VENT-3", name="Привод")
    await _login(api_client, OWNER_EMAIL)

    first = await api_client.post(
        MAPPINGS_URL, json=_body(product, client_sku="привод-2")
    )
    assert first.status_code == 201, first.text

    duplicate = await api_client.post(
        MAPPINGS_URL, json=_body(product, client_sku="ПРИВОД-2")
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "CLIENT_SKU_MAPPING_EXISTS"


async def test_list_query_filter_by_client_sku_and_product_sku(
    api_client, session_factory
):
    """query ищет и по clientSku, и по нашему SKU (ILIKE, §16 п.43)."""
    organization = await create_organization(session_factory, legal_name="Csku Query Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    product_a = await _product(session_factory, sku="VENT-10", name="Вентилятор")
    product_b = await _product(session_factory, sku="MTR-20", name="Мотор")
    await _login(api_client, OWNER_EMAIL)
    first = await api_client.post(
        MAPPINGS_URL, json=_body(product_a, client_sku="вентляпка")
    )
    assert first.status_code == 201, first.text
    second = await api_client.post(
        MAPPINGS_URL, json=_body(product_b, client_sku="моторчик")
    )
    assert second.status_code == 201, second.text

    by_client = await api_client.get(MAPPINGS_URL, params={"query": "вент"})
    assert by_client.status_code == 200
    assert [row["clientSku"] for row in by_client.json()["data"]] == ["вентляпка"]

    by_product_sku = await api_client.get(MAPPINGS_URL, params={"query": "mtr"})
    assert by_product_sku.status_code == 200
    assert [row["clientSku"] for row in by_product_sku.json()["data"]] == ["моторчик"]

    empty = await api_client.get(MAPPINGS_URL, params={"query": "неттакого"})
    assert empty.status_code == 200
    assert empty.json()["data"] == []
    assert empty.json()["meta"]["total"] == 0


async def test_patch_if_match_and_stale_version(api_client, session_factory):
    """PATCH с If-Match по версии маппинга; stale → 409 STALE_RESOURCE_VERSION."""
    organization = await create_organization(session_factory, legal_name="Csku Patch Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    product = await _product(session_factory, sku="VENT-4", name="Привод 4")
    other = await _product(session_factory, sku="VENT-5", name="Привод 5")
    await _login(api_client, OWNER_EMAIL)
    created = await api_client.post(MAPPINGS_URL, json=_body(product, note="памятка"))
    assert created.status_code == 201, created.text
    mapping_id = created.json()["data"]["id"]

    patched = await api_client.patch(
        f"{MAPPINGS_URL}/{mapping_id}",
        json={"productId": str(other.id), "note": None},
        headers={"If-Match": "1"},
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()["data"]
    assert data["productId"] == str(other.id)
    assert data["note"] is None  # null у nullable-колонки очищает
    assert data["version"] == 2

    stale = await api_client.patch(
        f"{MAPPINGS_URL}/{mapping_id}",
        json={"note": "ещё правка"},
        headers={"If-Match": "1"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"

    missing = await api_client.patch(
        f"{MAPPINGS_URL}/{mapping_id}", json={"note": "без If-Match"}
    )
    assert missing.status_code == 400, missing.text
    assert missing.json()["code"] == "INVALID_IF_MATCH"


async def test_delete_204_then_404(api_client, session_factory):
    """DELETE (без If-Match) → 204; повторный DELETE той же связки → 404."""
    organization = await create_organization(session_factory, legal_name="Csku Del Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    product = await _product(session_factory, sku="VENT-6", name="Привод 6")
    await _login(api_client, OWNER_EMAIL)
    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    mapping_id = created.json()["data"]["id"]

    deleted = await api_client.delete(f"{MAPPINGS_URL}/{mapping_id}")
    assert deleted.status_code == 204, deleted.text

    listed = await api_client.get(MAPPINGS_URL)
    assert listed.json()["data"] == []

    again = await api_client.delete(f"{MAPPINGS_URL}/{mapping_id}")
    assert again.status_code == 404, again.text
    assert again.json()["code"] == "CLIENT_SKU_MAPPING_NOT_FOUND"


async def test_viewer_reads_but_cannot_write(api_client, session_factory):
    """VIEWER: чтение ок, мутации → 403 PERMISSION_DENIED (§16 п.43 п.6)."""
    organization = await create_organization(session_factory, legal_name="Csku View Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _member_user(
        session_factory,
        email=VIEWER_EMAIL,
        organization=organization,
        role=OrganizationRole.VIEWER,
    )
    product = await _product(session_factory, sku="VENT-7", name="Привод 7")
    await _login(api_client, OWNER_EMAIL)
    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    mapping_id = created.json()["data"]["id"]

    await _login(api_client, VIEWER_EMAIL)
    listed = await api_client.get(MAPPINGS_URL)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["data"]) == 1

    forbidden_post = await api_client.post(MAPPINGS_URL, json=_body(product))
    assert forbidden_post.status_code == 403, forbidden_post.text
    assert forbidden_post.json()["code"] == "PERMISSION_DENIED"

    forbidden_patch = await api_client.patch(
        f"{MAPPINGS_URL}/{mapping_id}", json={"note": "x"}, headers={"If-Match": "1"}
    )
    assert forbidden_patch.status_code == 403, forbidden_patch.text

    forbidden_delete = await api_client.delete(f"{MAPPINGS_URL}/{mapping_id}")
    assert forbidden_delete.status_code == 403, forbidden_delete.text


async def test_contact_reads_but_cannot_write(api_client, session_factory):
    """CONTACT: чтение ок, запись → 403."""
    organization = await create_organization(session_factory, legal_name="Csku Contact Org")
    await _member_user(
        session_factory,
        email=CONTACT_EMAIL,
        organization=organization,
        role=OrganizationRole.CONTACT,
    )
    product = await _product(session_factory, sku="VENT-8", name="Привод 8")
    await _login(api_client, CONTACT_EMAIL)

    listed = await api_client.get(MAPPINGS_URL)
    assert listed.status_code == 200, listed.text

    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    assert created.status_code == 403, created.text
    assert created.json()["code"] == "PERMISSION_DENIED"


async def test_solo_client_without_organization_422(api_client, session_factory):
    """USER-скоуп (соло-клиент без орги): режим недоступен → 422 ORGANIZATION_REQUIRED."""
    await create_user(
        session_factory, email=SOLO_EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    product = await _product(session_factory, sku="VENT-9", name="Привод 9")
    await _login(api_client, SOLO_EMAIL)

    listed = await api_client.get(MAPPINGS_URL)
    assert listed.status_code == 422, listed.text
    assert listed.json()["code"] == "ORGANIZATION_REQUIRED"

    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    assert created.status_code == 422, created.text
    assert created.json()["code"] == "ORGANIZATION_REQUIRED"

    applied = await api_client.post(
        f"{MAPPINGS_URL}/apply-csv", json={"csv": "vent=1\n"}
    )
    assert applied.status_code == 422, applied.text
    assert applied.json()["code"] == "ORGANIZATION_REQUIRED"


async def test_mapping_to_archived_product_422(api_client, session_factory):
    """Маппинг на ARCHIVED товар → 422 PRODUCT_ARCHIVED (§16 п.43 п.4)."""
    organization = await create_organization(session_factory, legal_name="Csku Arch Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    product = await _product(
        session_factory, sku="VENT-ARC", name="Архивный привод", stock=StockStatus.ARCHIVED
    )
    await _login(api_client, OWNER_EMAIL)

    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    assert created.status_code == 422, created.text
    assert created.json()["code"] == "PRODUCT_ARCHIVED"


async def test_mapping_to_unknown_product_404(api_client, session_factory):
    """Несуществующий productId → 404 PRODUCT_NOT_FOUND."""
    organization = await create_organization(session_factory, legal_name="Csku 404 Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _login(api_client, OWNER_EMAIL)

    created = await api_client.post(
        MAPPINGS_URL,
        json=_body_uuid_only(client_sku="vent", product_id=str(uuid.uuid4())),
    )
    assert created.status_code == 404, created.text
    assert created.json()["code"] == "PRODUCT_NOT_FOUND"


async def test_manager_crud_on_foreign_organization(api_client, session_factory):
    """staff (MANAGER) ведёт справочник чужой организации, org — из пути."""
    organization = await create_organization(session_factory, legal_name="Csku Managed Org")
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    product = await _product(session_factory, sku="VENT-11", name="Привод 11")
    await _login(api_client, MANAGER_EMAIL)

    created = await api_client.post(
        f"{MANAGER_MAPPINGS_URL}/{organization.id}/client-sku-mappings",
        json=_body(product, client_sku="вент-11", note="заводское соответствие"),
    )
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["organizationId"] == str(organization.id)
    mapping_id = data["id"]

    listed = await api_client.get(
        f"{MANAGER_MAPPINGS_URL}/{organization.id}/client-sku-mappings"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1

    patched = await api_client.patch(
        f"{MANAGER_MAPPINGS_URL}/{organization.id}/client-sku-mappings/{mapping_id}",
        json={"note": "обновлено менеджером"},
        headers={"If-Match": "1"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["version"] == 2

    deleted = await api_client.delete(
        f"{MANAGER_MAPPINGS_URL}/{organization.id}/client-sku-mappings/{mapping_id}"
    )
    assert deleted.status_code == 204, deleted.text


async def test_manager_router_forbidden_for_client(api_client, session_factory):
    """Клиент на manager-роутере → 403 (require_role MANAGER)."""
    organization = await create_organization(session_factory, legal_name="Csku NoStaff Org")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _login(api_client, OWNER_EMAIL)

    listed = await api_client.get(
        f"{MANAGER_MAPPINGS_URL}/{organization.id}/client-sku-mappings"
    )
    assert listed.status_code == 403, listed.text
    assert listed.json()["code"] == "PERMISSION_DENIED"


async def test_manager_nonexistent_organization_404(api_client, session_factory):
    """staff создаёт связку в несуществующей организации → 404."""
    await create_user(
        session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    product = await _product(session_factory, sku="VENT-12", name="Привод 12")
    await _login(api_client, MANAGER_EMAIL)

    created = await api_client.post(
        f"{MANAGER_MAPPINGS_URL}/{uuid.uuid4()}/client-sku-mappings",
        json=_body(product),
    )
    assert created.status_code == 404, created.text
    assert created.json()["code"] == "ORGANIZATION_NOT_FOUND"


async def test_cross_organization_isolation(api_client, session_factory):
    """Владелец орги A не видит и не правит связки орги B (404)."""
    org_a = await create_organization(session_factory, legal_name="Csku Org A")
    org_b = await create_organization(session_factory, legal_name="Csku Org B")
    await _member_user(
        session_factory,
        email=OWNER_EMAIL,
        organization=org_a,
        role=OrganizationRole.OWNER,
    )
    owner_b = await _member_user(
        session_factory,
        email=BUYER_EMAIL,
        organization=org_b,
        role=OrganizationRole.OWNER,
    )
    product = await _product(session_factory, sku="VENT-13", name="Привод 13")
    await set_active_organization(
        session_factory, user=owner_b, organization=org_b
    )
    await _login(api_client, BUYER_EMAIL)
    created = await api_client.post(MAPPINGS_URL, json=_body(product))
    assert created.status_code == 201, created.text
    foreign_id = created.json()["data"]["id"]

    await _login(api_client, OWNER_EMAIL)
    foreign_get = await api_client.get(
        MAPPINGS_URL, params={"query": "Привод ГТУ-2"}
    )
    assert foreign_get.status_code == 200
    assert foreign_get.json()["data"] == []

    foreign_patch = await api_client.patch(
        f"{MAPPINGS_URL}/{foreign_id}", json={"note": "hack"}, headers={"If-Match": "1"}
    )
    assert foreign_patch.status_code == 404, foreign_patch.text

    foreign_delete = await api_client.delete(f"{MAPPINGS_URL}/{foreign_id}")
    assert foreign_delete.status_code == 404, foreign_delete.text
