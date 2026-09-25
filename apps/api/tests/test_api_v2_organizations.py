"""Focused API v2 organization control-plane and session selection tests."""
import pytest
from sqlalchemy import select

from app.models.enums import OrganizationRole, UserRole
from app.models.organization import Organization
from app.models.system import AuditLog
from tests.conftest import (
    add_organization_membership,
    create_organization,
    create_user,
)

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!"


async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _manager(api_client, session_factory, *, email="org-manager@example.by"):
    manager = await create_user(session_factory, email=email, role=UserRole.MANAGER)
    await _login(api_client, email)
    return manager


async def test_organization_list_cursor_search_sort_and_invalid_cursor(
    api_client, session_factory
):
    await _manager(api_client, session_factory)
    alpha = await create_organization(session_factory, legal_name="Alpha Org")
    bravo = await create_organization(session_factory, legal_name="Bravo Org")
    await create_organization(session_factory, legal_name="Charlie Org")
    async with session_factory() as db:
        taxable = Organization(
            legal_name="Taxable Org",
            display_name="Tax Display",
            tax_id="UNP-777",
        )
        db.add(taxable)
        await db.commit()
        await db.refresh(taxable)

    first = await api_client.get(
        "/api/v2/organizations", params={"sort": "legalName", "limit": 1}
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["data"][0]["id"] == str(alpha.id)
    assert first_body["data"][0]["legalName"] == "Alpha Org"
    assert first_body["meta"]["hasMore"] is True
    assert first_body["meta"]["sort"] == "legalName"
    assert "total" not in first_body["meta"]

    second = await api_client.get(
        "/api/v2/organizations",
        params={
            "sort": "legalName",
            "limit": 1,
            "cursor": first_body["meta"]["nextCursor"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"][0]["id"] == str(bravo.id)

    reverse = await api_client.get(
        "/api/v2/organizations", params={"sort": "-legalName", "limit": 2}
    )
    assert reverse.status_code == 200, reverse.text
    assert [item["legalName"] for item in reverse.json()["data"]] == [
        "Taxable Org",
        "Charlie Org",
    ]

    searched = await api_client.get(
        "/api/v2/organizations", params={"q": "UNP-777", "limit": 1}
    )
    assert searched.status_code == 200, searched.text
    assert [item["id"] for item in searched.json()["data"]] == [str(taxable.id)]

    wrong_sort = await api_client.get(
        "/api/v2/organizations",
        params={
            "sort": "-legalName",
            "cursor": first_body["meta"]["nextCursor"],
        },
    )
    assert wrong_sort.status_code == 422, wrong_sort.text
    assert wrong_sort.json()["code"] == "VALIDATION_ERROR"
    tampered = first_body["meta"]["nextCursor"]
    tampered = f"{tampered[:-1]}{'A' if tampered[-1] != 'A' else 'B'}"
    invalid = await api_client.get(
        "/api/v2/organizations", params={"cursor": tampered}
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.headers["content-type"].startswith("application/problem+json")
    assert invalid.json()["code"] == "VALIDATION_ERROR"


async def test_member_list_cursor_search_and_reverse_sort(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Paged Members")
    users = [
        await create_user(
            session_factory,
            email=email,
            role=UserRole.CLIENT,
        )
        for email in ("zoe@example.by", "adam@example.by", "mira@example.by")
    ]
    for user in users:
        await add_organization_membership(
            session_factory, user=user, organization=organization
        )
    await _manager(api_client, session_factory)

    first = await api_client.get(
        f"/api/v2/organizations/{organization.id}/members",
        params={"sort": "fullName", "limit": 1},
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"][0]["fullName"] == "Adam"
    assert first.json()["meta"]["hasMore"] is True

    second = await api_client.get(
        f"/api/v2/organizations/{organization.id}/members",
        params={
            "sort": "fullName",
            "limit": 1,
            "cursor": first.json()["meta"]["nextCursor"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"][0]["fullName"] == "Mira"

    searched = await api_client.get(
        f"/api/v2/organizations/{organization.id}/members",
        params={"q": "zoe@", "sort": "-email", "limit": 1},
    )
    assert searched.status_code == 200, searched.text
    assert [item["email"] for item in searched.json()["data"]] == ["zoe@example.by"]
    assert searched.json()["meta"]["nextCursor"] is None

    wrong_resource = await api_client.get(
        "/api/v2/organizations",
        params={"cursor": first.json()["meta"]["nextCursor"]},
    )
    assert wrong_resource.status_code == 422, wrong_resource.text
    assert wrong_resource.json()["code"] == "VALIDATION_ERROR"
async def test_manager_list_and_detail_are_control_plane_only(
    api_client, session_factory
):
    await _manager(api_client, session_factory)
    organization = await create_organization(session_factory, legal_name="Managed Org")

    listed = await api_client.get("/api/v2/organizations")
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["data"]] == [str(organization.id)]

    detail = await api_client.get(f"/api/v2/organizations/{organization.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["legalName"] == "Managed Org"
    assert detail.json()["data"]["version"] == 1
    assert "passwordHash" not in detail.text
    assert "fixedRateId" not in detail.text


async def test_anonymous_and_client_are_denied_manager_list(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Denied Org")
    anonymous = await api_client.get("/api/v2/organizations")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "AUTHENTICATION_REQUIRED"

    await create_user(
        session_factory, email="org-client@example.by", role=UserRole.CLIENT
    )
    await _login(api_client, "org-client@example.by")
    denied = await api_client.get(f"/api/v2/organizations/{organization.id}")
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"


async def test_members_add_existing_client_and_duplicate_conflict(
    api_client, session_factory
):
    organization = await create_organization(session_factory, legal_name="Member Org")
    client = await create_user(
        session_factory, email="member-target@example.by", role=UserRole.CLIENT
    )
    await _manager(api_client, session_factory)

    listed = await api_client.get(f"/api/v2/organizations/{organization.id}/members")
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"] == []

    added = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(client.id), "role": "BUYER"},
    )
    assert added.status_code == 201, added.text
    assert added.json()["data"]["userId"] == str(client.id)
    assert added.json()["data"]["version"] == 1

    duplicate = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(client.id)},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "MEMBERSHIP_ALREADY_EXISTS"


async def test_member_add_and_update_audits_use_membership_snapshots(
    api_client, session_factory
):
    organization = await create_organization(session_factory, legal_name="Audit Org")
    target = await create_user(
        session_factory, email="audit-target@example.by", role=UserRole.CLIENT
    )
    manager = await _manager(api_client, session_factory, email="audit-manager@example.by")

    added = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(target.id), "role": "BUYER"},
    )
    assert added.status_code == 201, added.text

    updated = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/{target.id}",
        headers={"If-Match": "1"},
        json={"role": "CONTACT", "isPrimary": True},
    )
    assert updated.status_code == 200, updated.text

    async with session_factory() as db:
        entries = list(
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.target_id == target.id)
                )
            )
            .scalars()
            .all()
        )

    assert {entry.action for entry in entries} == {
        "organization.membership.add",
        "organization.membership.update",
    }
    entries_by_action = {entry.action: entry for entry in entries}
    added_entry = entries_by_action["organization.membership.add"]
    updated_entry = entries_by_action["organization.membership.update"]
    expected_base = {
        "organizationId": str(organization.id),
        "role": "BUYER",
        "isActive": True,
        "isPrimary": False,
        "version": 1,
    }
    assert added_entry.actor_id == manager.id
    assert added_entry.target_type == "organization_membership"
    assert added_entry.before is None
    assert added_entry.after == expected_base
    assert updated_entry.actor_id == manager.id
    assert updated_entry.target_type == "organization_membership"
    assert updated_entry.before == expected_base
    assert updated_entry.after == {
        **expected_base,
        "role": "CONTACT",
        "isPrimary": True,
        "version": 2,
    }


async def test_manager_cannot_be_added_as_commercial_member(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Staff Org")
    target = await create_user(
        session_factory, email="staff-target@example.by", role=UserRole.MANAGER
    )
    await _manager(api_client, session_factory, email="staff-control@example.by")

    response = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(target.id)},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "MEMBERSHIP_TARGET_INVALID"


async def test_membership_patch_uses_if_match_and_rejects_stale_version(
    api_client, session_factory
):
    organization = await create_organization(session_factory, legal_name="Patch Org")
    target = await create_user(
        session_factory, email="patch-target@example.by", role=UserRole.CLIENT
    )
    await _manager(api_client, session_factory)
    added = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(target.id)},
    )
    assert added.status_code == 201, added.text

    updated = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/{target.id}",
        headers={"If-Match": 'W/"1"'},
        json={"isPrimary": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["isPrimary"] is True
    assert updated.json()["data"]["version"] == 2

    stale = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/{target.id}",
        headers={"If-Match": "1"},
        json={"isPrimary": False},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"

    async with session_factory() as db:
        actions = list(
            (
                await db.execute(
                    select(AuditLog.action).where(AuditLog.target_id == target.id)
                )
            )
            .scalars()
            .all()
        )
    assert set(actions) == {
        "organization.membership.add",
        "organization.membership.update",
    }
    assert len(actions) == 2


async def test_membership_patch_requires_well_formed_if_match(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="If-Match Org")
    target = await create_user(
        session_factory, email="if-match-target@example.by", role=UserRole.CLIENT
    )
    await _manager(api_client, session_factory, email="if-match-manager@example.by")
    added = await api_client.post(
        f"/api/v2/organizations/{organization.id}/members",
        json={"userId": str(target.id)},
    )
    assert added.status_code == 201, added.text

    missing = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/{target.id}",
        json={"isPrimary": True},
    )
    assert missing.status_code == 400, missing.text
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "INVALID_IF_MATCH"

    malformed = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/{target.id}",
        headers={"If-Match": "not-a-version"},
        json={"isPrimary": True},
    )
    assert malformed.status_code == 400, malformed.text
    assert malformed.headers["content-type"].startswith("application/problem+json")
    assert malformed.json()["code"] == "INVALID_IF_MATCH"

    not_found = await api_client.patch(
        f"/api/v2/organizations/{organization.id}/members/"
        "00000000-0000-0000-0000-000000000001",
        headers={"If-Match": "1"},
        json={"isPrimary": True},
    )
    assert not_found.status_code == 404, not_found.text
    assert not_found.json()["code"] == "MEMBERSHIP_NOT_FOUND"

    async with session_factory() as db:
        actions = list(
            (
                await db.execute(
                    select(AuditLog.action).where(
                        AuditLog.target_type == "organization_membership"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["organization.membership.add"]


async def test_last_active_owner_cannot_be_deactivated_or_downgraded(
    api_client, session_factory
):
    organization = await create_organization(session_factory, legal_name="Owner Org")
    owner = await create_user(
        session_factory, email="last-owner@example.by", role=UserRole.CLIENT
    )
    await add_organization_membership(
        session_factory,
        user=owner,
        organization=organization,
        role=OrganizationRole.OWNER,
    )
    await _manager(api_client, session_factory)

    for payload in ({"isActive": False}, {"role": "BUYER"}):
        response = await api_client.patch(
            f"/api/v2/organizations/{organization.id}/members/{owner.id}",
            headers={"If-Match": "1"},
            json=payload,
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "LAST_OWNER_PROTECTED"

    async with session_factory() as db:
        entries = list(
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.target_id == owner.id)
                )
            )
            .scalars()
            .all()
        )
    assert entries == []


async def test_active_organization_selection_valid_invalid_and_null(
    api_client, session_factory
):
    organization = await create_organization(session_factory, legal_name="Select Org")
    user = await create_user(
        session_factory, email="select-client@example.by", role=UserRole.CLIENT
    )
    await add_organization_membership(
        session_factory, user=user, organization=organization
    )
    await _login(api_client, "select-client@example.by")

    valid = await api_client.put(
        "/api/v2/session/organization",
        json={"organizationId": str(organization.id)},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["data"]["commercialScope"] == "ORGANIZATION"
    assert valid.json()["data"]["organizationId"] == str(organization.id)

    invalid = await api_client.put(
        "/api/v2/session/organization",
        json={"organizationId": "00000000-0000-0000-0000-000000000001"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "ORGANIZATION_SELECTION_INVALID"

    cleared = await api_client.put(
        "/api/v2/session/organization", json={"organizationId": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["commercialScope"] == "USER"
    assert cleared.json()["data"]["organizationId"] is None


async def test_inactive_organization_cannot_be_selected(api_client, session_factory):
    organization = await create_organization(session_factory, legal_name="Inactive Org")
    user = await create_user(
        session_factory, email="inactive-client@example.by", role=UserRole.CLIENT
    )
    await add_organization_membership(
        session_factory, user=user, organization=organization
    )
    async with session_factory() as db:
        db_org = await db.get(Organization, organization.id)
        db_org.is_active = False
        await db.commit()
    await _login(api_client, "inactive-client@example.by")

    response = await api_client.put(
        "/api/v2/session/organization",
        json={"organizationId": str(organization.id)},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ORGANIZATION_SELECTION_INVALID"
