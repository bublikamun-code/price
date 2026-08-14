"""Тесты заявок клиента. См. §6, §9, §17.2 (снапшот цен/курса).

Ключевая проверка: цена и курс замораживаются при оформлении и НЕ
пересчитываются при последующих изменениях прайса/скидки/курса.
"""
import uuid

from sqlalchemy import select

from app.models.enums import OrderStatus, StockStatus, UserRole
from app.models.order import Order
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
    set_discount,
    set_fixed_rate_for_user,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
OTHER_EMAIL = "other@example.by"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed(sf):
    brand = await create_brand(sf, name="Alpha")
    series = await create_series(sf, brand=brand, name="Serie X")
    p1 = await create_product(sf, sku="A-1", name="Widget", brand=brand, series=series, base_price=100)
    p2 = await create_product(sf, sku="A-2", name="Gadget", brand=brand, series=series, base_price=50,
                              stock=StockStatus.ARCHIVED)
    return brand, p1, p2


# =========================================================
# CREATE
# =========================================================
async def test_create_order(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [{"sku": "A-1", "quantity": 3}], "notes": "срочно"
    })
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["status"] == "NEW"
    assert o["total_amount"] == 300.0
    assert o["notes"] == "срочно"
    assert o["currency_code"] == "BYN"
    assert o["exchange_rate"] == 1.0
    assert len(o["items"]) == 1
    assert o["items"][0]["unit_price"] == 100.0
    assert o["items"][0]["quantity"] == 3
    assert o["items"][0]["product_snapshot"]["sku"] == "A-1"


async def test_create_archived_forbidden(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-2", "quantity": 1}]})
    assert r.status_code == 400


async def test_create_unknown_sku(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "NOPE", "quantity": 1}]})
    assert r.status_code == 404


# =========================================================
# SNAPSHOT — цена замораживается
# =========================================================
async def test_price_snapshot_freezes_after_price_change(api_client, session_factory):
    sf = session_factory
    brand, p1, _ = await _seed(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand, percent=10)  # клиентская цена = 90
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}]})
    assert r.status_code == 201
    order_id = r.json()["id"]
    frozen_unit_price = r.json()["items"][0]["unit_price"]
    assert frozen_unit_price == 90.0

    # Меняем прайс и убираем скидку ПОСЛЕ оформления.
    from app.models.catalog import Product
    from app.models.pricing import UserBrand
    async with sf() as s:
        prod = await s.get(Product, p1.id)
        prod.base_price = 999  # резко дороже
        await s.execute(select(UserBrand).where(UserBrand.user_id == user.id))
        ub = (await s.execute(select(UserBrand).where(UserBrand.user_id == user.id))).scalar_one_or_none()
        if ub:
            ub.discount_percent = 0
        await s.commit()

    # Замороженная цена в заказе НЕ изменилась.
    r = await api_client.get(f"/api/v1/orders/{order_id}")
    assert r.json()["items"][0]["unit_price"] == 90.0
    assert r.json()["total_amount"] == 90.0


# =========================================================
# SNAPSHOT — курс фиксируется
# =========================================================
async def test_exchange_rate_snapshot(api_client, session_factory):
    sf = session_factory
    brand, p1, _ = await _seed(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    rate = await set_rate(sf, currency="USD", rate=3, scale=1)
    await set_fixed_rate_for_user(sf, user=user, rate=rate)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [{"sku": "A-1", "quantity": 2}], "price_calc_mode": "fixed"
    })
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["currency_code"] == "USD"
    assert o["exchange_rate"] == 3.0
    assert o["rate_source"] == "FIXED"
    # unit_price в display-валюте: 100 BYN * 1 / 3 ≈ 33.33
    assert abs(o["items"][0]["unit_price"] - 33.33) < 0.01


# =========================================================
# LIST / GET / RBAC
# =========================================================
async def test_list_only_own_orders(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await create_user(sf, email=OTHER_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    await _login(api_client, CLIENT_EMAIL)
    await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}]})

    await _login(api_client, OTHER_EMAIL)
    await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 2}]})

    # other видит только свой (1 заказ)
    r = await api_client.get("/api/v1/orders")
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["total_amount"] == 200.0


async def test_get_other_clients_order_returns_404(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await create_user(sf, email=OTHER_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}]})).json()["id"]

    # other не должен видеть заказ client
    await _login(api_client, OTHER_EMAIL)
    r = await api_client.get(f"/api/v1/orders/{order_id}")
    assert r.status_code == 404


# =========================================================
# CANCEL / FSM
# =========================================================
async def test_cancel_new_order(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}]})).json()["id"]

    r = await api_client.post(f"/api/v1/orders/{order_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


async def test_cancel_completed_conflict(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}]})).json()["id"]

    # Симулируем завершённый статус напрямую в БД (менеджер довёл до COMPLETED).
    async with sf() as s:
        order = await s.get(Order, uuid.UUID(order_id))
        order.status = OrderStatus.COMPLETED
        await s.commit()

    r = await api_client.post(f"/api/v1/orders/{order_id}/cancel")
    assert r.status_code == 409


# =========================================================
# REPEAT (фича C)
# =========================================================
async def test_repeat_order_fills_cart(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 4}]})).json()["id"]

    r = await api_client.post(f"/api/v1/orders/{order_id}/repeat")
    assert r.status_code == 200, r.text
    cart = r.json()
    assert cart["total_items"] == 1
    assert cart["items"][0]["sku"] == "A-1"
    assert cart["items"][0]["quantity"] == 4
