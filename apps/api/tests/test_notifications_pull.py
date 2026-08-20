"""Тесты pull-ленты in-app уведомлений (§6 «Уведомления», §16 п.20-4).

Сценарии: свои уведомления + broadcast всем менеджерам (user_id IS NULL);
unread_count — только «свои»; прочитанным можно отметить только своё.
"""
import uuid

from app.models.enums import UserRole
from app.repositories.notifications import create_notification
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
CLIENT2_EMAIL = "client2@example.by"
MANAGER_EMAIL = "manager@example.by"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed(
    session_factory,
    *,
    type: str = "ORDER_CREATED",
    title: str | None = None,
    user_id: uuid.UUID | None = None,
    payload: dict | None = None,
    read: bool = False,
) -> str:
    """Создать уведомление через repo-хелпер (flush + commit). Возвращает id строкой
    (как он приходит в JSON)."""
    async with session_factory() as s:
        notif = await create_notification(
            s, type=type, title=title, body=None, user_id=user_id, payload=payload
        )
        if read:
            notif.is_read = True
        await s.commit()
        return str(notif.id)


async def _get(api_client, params: dict | None = None):
    r = await api_client.get("/api/v1/notifications", params=params or {})
    assert r.status_code == 200, r.text
    return r.json()


async def test_requires_auth(api_client):
    r = await api_client.get("/api/v1/notifications")
    assert r.status_code == 401


async def test_client_sees_only_own(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    other = await create_user(sf, email=CLIENT2_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    own_ids = {await _seed(sf, type="ORDER_CREATED", user_id=user.id) for _ in range(2)}
    await _seed(sf, type="ORDER_CREATED", user_id=other.id)  # чужое
    await _seed(sf, type="IMPORT_DONE")  # broadcast

    await _login(api_client, CLIENT_EMAIL)
    body = await _get(api_client)

    assert body["meta"]["total"] == 2
    assert {n["id"] for n in body["data"]} == own_ids
    assert all(n["is_broadcast"] is False for n in body["data"])
    assert body["meta"]["unread_count"] == 2  # только свои непрочитанные


async def test_manager_sees_own_and_broadcast(api_client, session_factory):
    sf = session_factory
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    client = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    own_id = await _seed(sf, type="NEW_ORDER", user_id=manager.id, payload={"order_id": "x"})
    await _seed(sf, type="ORDER_CREATED", user_id=client.id)  # чужое — не видно
    b1 = await _seed(sf, type="IMPORT_DONE")  # broadcast
    b2 = await _seed(sf, type="USER_REGISTERED")  # broadcast прочитанным сделать нельзя

    await _login(api_client, MANAGER_EMAIL)
    body = await _get(api_client)

    ids = {n["id"] for n in body["data"]}
    assert body["meta"]["total"] == 3
    assert ids == {own_id, b1, b2}
    by_id = {n["id"]: n for n in body["data"]}
    assert by_id[own_id]["is_broadcast"] is False
    assert by_id[own_id]["payload"] == {"order_id": "x"}
    broadcast = [n for n in body["data"] if n["id"] != own_id]
    assert len(broadcast) == 2
    assert all(n["is_broadcast"] is True and n["is_read"] is False for n in broadcast)
    # unread_count — только свои: broadcast (даже непрочитанные) не считаются
    assert body["meta"]["unread_count"] == 1


async def test_type_and_unread_filters(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    a_unread = await _seed(sf, type="ORDER_CREATED", user_id=user.id)
    a_read = await _seed(sf, type="ORDER_CREATED", user_id=user.id, read=True)
    b_unread = await _seed(sf, type="PRICE_CHANGED", user_id=user.id)

    await _login(api_client, CLIENT_EMAIL)

    body = await _get(api_client, {"type": "ORDER_CREATED"})
    assert {n["id"] for n in body["data"]} == {a_unread, a_read}
    assert body["meta"]["total"] == 2

    body = await _get(api_client, {"unread_only": True})
    assert {n["id"] for n in body["data"]} == {a_unread, b_unread}

    body = await _get(api_client, {"type": "PRICE_CHANGED", "unread_only": True})
    assert {n["id"] for n in body["data"]} == {b_unread}


async def test_pagination_meta(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    for _ in range(3):
        await _seed(sf, user_id=user.id)

    await _login(api_client, CLIENT_EMAIL)

    body = await _get(api_client, {"page": 1, "per_page": 2})
    assert len(body["data"]) == 2
    assert body["meta"] == {"page": 1, "per_page": 2, "total": 3, "unread_count": 3}

    body = await _get(api_client, {"page": 2, "per_page": 2})
    assert len(body["data"]) == 1
    assert body["meta"]["total"] == 3

    r = await api_client.get("/api/v1/notifications", params={"per_page": 201})
    assert r.status_code == 422


async def test_mark_read_own(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    own_id = await _seed(sf, user_id=user.id)

    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.patch(f"/api/v1/notifications/{own_id}/read")
    assert r.status_code == 200, r.text
    assert r.json()["is_read"] is True

    body = await _get(api_client)
    assert body["meta"]["unread_count"] == 0


async def test_mark_read_foreign_404(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    other = await create_user(sf, email=CLIENT2_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    foreign_id = await _seed(sf, user_id=other.id)

    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.patch(f"/api/v1/notifications/{foreign_id}/read")
    assert r.status_code == 404


async def test_mark_read_broadcast_404_even_for_manager(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    broadcast_id = await _seed(sf)  # user_id IS NULL

    await _login(api_client, MANAGER_EMAIL)
    r = await api_client.patch(f"/api/v1/notifications/{broadcast_id}/read")
    assert r.status_code == 404


async def test_read_all_marks_only_own(api_client, session_factory):
    sf = session_factory
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    for _ in range(2):
        await _seed(sf, user_id=manager.id)
    await _seed(sf, type="IMPORT_DONE")  # broadcast остаётся непрочитанным

    await _login(api_client, MANAGER_EMAIL)
    r = await api_client.patch("/api/v1/notifications/read-all")
    assert r.status_code == 204

    body = await _get(api_client)
    assert body["meta"]["unread_count"] == 0

    # broadcast в ленте менеджера остаётся непрочитанным
    broadcasts = [n for n in body["data"] if n["is_broadcast"]]
    assert len(broadcasts) == 1
    assert broadcasts[0]["is_read"] is False

    body = await _get(api_client, {"unread_only": True})
    assert {n["id"] for n in body["data"]} == {broadcasts[0]["id"]}
