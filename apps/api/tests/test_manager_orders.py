"""Тесты заявок менеджера. См. §6, §9 (FSM), §11 (RBAC, audit_log)."""
import uuid

from sqlalchemy import select

from app.models.enums import UserRole
from app.models.system import AuditLog
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed_and_order(sf, api_client):
    """Создаёт каталог + клиента + менеджера; возвращает (order_id, manager_id, client_user)."""
    brand = await create_brand(sf, name="Alpha")
    series = await create_series(sf, brand=brand, name="Serie X")
    await create_product(sf, sku="A-1", name="Widget", brand=brand, series=series, base_price=100)
    client = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)

    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 2}], "delivery_point": "Склад Минск"})).json()["id"]
    return order_id, manager, client


async def test_manager_list_requires_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.get("/api/v1/manager/orders")).status_code == 403


async def test_manager_lists_all_orders(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.get("/api/v1/manager/orders")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == order_id


async def test_manager_get_order(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.get(f"/api/v1/manager/orders/{order_id}")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


async def test_change_status_valid_transition(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.patch(f"/api/v1/manager/orders/{order_id}",
                               json={"status": "IN_PROGRESS", "manager_id": str(manager.id)})
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "IN_PROGRESS"
    assert o["manager_id"] == str(manager.id)


async def test_change_status_invalid_transition_conflict(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    # NEW → COMPLETED запрещено (надо через IN_PROGRESS, SHIPPED)
    r = await api_client.patch(f"/api/v1/manager/orders/{order_id}", json={"status": "COMPLETED"})
    assert r.status_code == 409


async def test_change_status_writes_audit_log(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    await api_client.patch(f"/api/v1/manager/orders/{order_id}",
                           json={"status": "IN_PROGRESS", "manager_id": str(manager.id)})

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.target_id == uuid.UUID(order_id))
        )).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "order.status_change"
    assert entry.before["status"] == "NEW"
    assert entry.after["status"] == "IN_PROGRESS"
    assert entry.actor_id == manager.id
