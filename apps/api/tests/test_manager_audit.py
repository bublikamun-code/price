"""Тесты журнала аудита менеджер-панели. См. §5, §6, §16 п.19."""
from app.models.enums import UserRole
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


async def _login_manager(api_client, sf):
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": MANAGER_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return manager


async def test_audit_requires_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await api_client.post("/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD})
    assert (await api_client.get("/api/v1/manager/audit")).status_code == 403


async def test_audit_list_filters_and_actor_email(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)

    r = await api_client.post(
        "/api/v1/manager/users",
        json={"email": "audit@example.by", "full_name": "Аудит"},
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]

    r = await api_client.patch(
        f"/api/v1/manager/users/{user_id}", json={"phone": "+375291110011"}
    )
    assert r.status_code == 200, r.text

    r = await api_client.get("/api/v1/manager/audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] == 2
    actions = [row["action"] for row in body["data"]]
    assert actions == ["user.update", "user.create"]  # новые сверху
    assert all(row["actor_email"] == MANAGER_EMAIL for row in body["data"])
    assert all(row["actor_id"] == str(manager.id) for row in body["data"])
    created = [row["created_at"] for row in body["data"]]
    assert created == sorted(created, reverse=True)
    assert body["data"][0]["before"] == {"phone": None}
    assert body["data"][0]["after"] == {"phone": "+375291110011"}

    r = await api_client.get("/api/v1/manager/audit", params={"action": "user.update"})
    assert r.status_code == 200
    only_update = r.json()
    assert only_update["meta"]["total"] == 1
    assert only_update["data"][0]["action"] == "user.update"

    r = await api_client.get(
        "/api/v1/manager/audit", params={"target_type": "user", "per_page": 1}
    )
    assert r.json()["meta"]["total"] == 2
    assert len(r.json()["data"]) == 1

    r = await api_client.get(
        "/api/v1/manager/audit", params={"actor_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 0
