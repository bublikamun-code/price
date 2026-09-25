"""Тесты заявок менеджера. См. §6, §9 (FSM), §11 (RBAC, audit_log)."""
import uuid

from sqlalchemy import select

import app.api.v1.manager.orders as manager_orders_router
from app.models.catalog import Product
from app.models.enums import UserRole
from app.models.system import AuditLog
from app.models.user import User
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


class _FakeTg:
    """Фейк Celery-задачи send_telegram: записывает вызовы .delay()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def delay(self, chat_id: str, text: str) -> None:
        self.calls.append((chat_id, text))


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


async def test_change_status_with_if_match_rejects_stale_version(api_client, session_factory):
    """If-Match защищает manager update от перезаписи устаревшего статуса."""
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    first = await api_client.patch(
        f"/api/v1/manager/orders/{order_id}",
        json={"status": "IN_PROGRESS"},
        headers={"If-Match": '"1"'},
    )
    stale = await api_client.patch(
        f"/api/v1/manager/orders/{order_id}",
        json={"status": "SHIPPED"},
        headers={"If-Match": '"1"'},
    )

    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.headers["X-Error-Code"] == "STALE_RESOURCE_VERSION"


async def test_manager_confirmation_rechecks_stock_without_reserving(api_client, session_factory):
    """Manager confirmation проверяет текущий остаток, но не списывает его."""
    sf = session_factory
    order_id, _manager, _client = await _seed_and_order(sf, api_client)
    async with sf() as session:
        product = await session.scalar(
            select(Product).where(Product.sku == "A-1")
        )
        product.stock_qty = 1
        await session.commit()
    await _login(api_client, MANAGER_EMAIL)

    blocked = await api_client.patch(
        f"/api/v1/manager/orders/{order_id}", json={"status": "IN_PROGRESS"}
    )
    assert blocked.status_code == 422
    assert blocked.headers["X-Error-Code"] == "INSUFFICIENT_STOCK"

    async with sf() as session:
        product = await session.scalar(
            select(Product).where(Product.sku == "A-1")
        )
        product.stock_qty = 2
        await session.commit()
    accepted = await api_client.patch(
        f"/api/v1/manager/orders/{order_id}", json={"status": "IN_PROGRESS"}
    )
    assert accepted.status_code == 200, accepted.text
    async with sf() as session:
        product = await session.scalar(
            select(Product).where(Product.sku == "A-1")
        )
        assert product.stock_qty == 2


async def test_change_status_invalid_transition_conflict(api_client, session_factory):
    sf = session_factory
    order_id, manager, _ = await _seed_and_order(sf, api_client)
    await _login(api_client, MANAGER_EMAIL)

    # NEW → COMPLETED запрещено (надо через IN_PROGRESS, SHIPPED)
    r = await api_client.patch(f"/api/v1/manager/orders/{order_id}", json={"status": "COMPLETED"})
    assert r.status_code == 409
    assert r.headers["X-Error-Code"] == "INVALID_ORDER_TRANSITION"


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


async def test_change_status_notifies_bound_client_via_tg(
    api_client, session_factory, monkeypatch
):
    """Клиенту с привязанным telegram_id уходит TG о новом статусе (§20)."""
    sf = session_factory
    order_id, _manager, client = await _seed_and_order(sf, api_client)
    async with sf() as s:
        u = await s.get(User, client.id)
        u.telegram_id = 100200
        await s.commit()

    fake_tg = _FakeTg()
    monkeypatch.setattr(manager_orders_router, "send_telegram", fake_tg)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.patch(f"/api/v1/manager/orders/{order_id}",
                               json={"status": "IN_PROGRESS"})
    assert r.status_code == 200, r.text

    assert len(fake_tg.calls) == 1
    chat, text = fake_tg.calls[0]
    assert chat == "100200"
    assert "статус → В работе" in text  # IN_PROGRESS по ORDER_STATUS_RU


async def test_change_status_skips_tg_without_telegram(
    api_client, session_factory, monkeypatch
):
    """Клиент без telegram_id — TG-задача не ставится вовсе."""
    sf = session_factory
    order_id, _manager, _ = await _seed_and_order(sf, api_client)

    fake_tg = _FakeTg()
    monkeypatch.setattr(manager_orders_router, "send_telegram", fake_tg)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.patch(f"/api/v1/manager/orders/{order_id}",
                               json={"status": "IN_PROGRESS"})
    assert r.status_code == 200, r.text
    assert fake_tg.calls == []
