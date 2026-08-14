"""Тесты корзины (persist в БД). См. §19, §6 (/cart)."""

from app.models.enums import StockStatus, UserRole
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
    set_discount,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed(sf):
    brand = await create_brand(sf, name="Alpha")
    series = await create_series(sf, brand=brand, name="Serie X", photo_key="x.webp")
    p1 = await create_product(sf, sku="A-1", name="Widget", brand=brand, series=series, base_price=100)
    p2 = await create_product(sf, sku="A-2", name="Gadget", brand=brand, series=series, base_price=50,
                              stock=StockStatus.ARCHIVED)
    return brand, p1, p2


async def test_cart_requires_auth(api_client):
    r = await api_client.get("/api/v1/cart")
    assert r.status_code == 401


async def test_add_and_view(api_client, session_factory):
    sf = session_factory
    _, p1, _ = await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 2})
    assert r.status_code == 201, r.text
    cart = r.json()
    assert cart["total_items"] == 1
    item = cart["items"][0]
    assert item["sku"] == "A-1"
    assert item["quantity"] == 2
    assert item["unit_price"] == 100.0
    assert item["line_total"] == 200.0
    assert cart["total_amount"] == 200.0


async def test_add_archived_forbidden(api_client, session_factory):
    sf = session_factory
    _, _, p2 = await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-2", "quantity": 1})
    assert r.status_code == 400


async def test_add_unknown_sku(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/cart/items", json={"sku": "NOPE", "quantity": 1})
    assert r.status_code == 404


async def test_add_same_sku_accumulates(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 2})
    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 3})
    assert r.status_code == 201
    assert r.json()["items"][0]["quantity"] == 5


async def test_add_with_discount(api_client, session_factory):
    sf = session_factory
    brand, p1, _ = await _seed(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand, percent=10)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 1})
    assert r.json()["items"][0]["unit_price"] == 90.0  # 100 * (1 - 0.1)


async def test_update_and_delete_and_clear(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 1})

    r = await api_client.put("/api/v1/cart/items/A-1", json={"quantity": 7})
    assert r.json()["items"][0]["quantity"] == 7

    r = await api_client.put("/api/v1/cart/items/A-1", json={"note": "сертификат"})
    assert r.json()["items"][0]["note"] == "сертификат"

    r = await api_client.delete("/api/v1/cart/items/A-1")
    assert r.json()["total_items"] == 0

    # повторное удаление → 404
    r = await api_client.delete("/api/v1/cart/items/A-1")
    assert r.status_code == 404


async def test_clear_cart(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 1})
    r = await api_client.delete("/api/v1/cart")
    assert r.status_code == 200
    assert r.json()["total_items"] == 0
