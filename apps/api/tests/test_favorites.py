"""Тесты избранного. См. §16.1 (фича A)."""
from app.models.enums import UserRole
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _seed(sf):
    brand = await create_brand(sf, name="Alpha")
    series = await create_series(sf, brand=brand, name="Serie X")
    p1 = await create_product(sf, sku="A-1", name="Widget", brand=brand, series=series, base_price=100)
    p2 = await create_product(sf, sku="A-2", name="Gadget", brand=brand, series=series, base_price=50)
    return brand, p1, p2


async def test_favorites_requires_auth(api_client):
    assert (await api_client.get("/api/v1/favorites")).status_code == 401


async def test_add_list_delete(api_client, session_factory):
    sf = session_factory
    _, p1, p2 = await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/favorites", json={"sku": "A-1"})
    assert r.status_code == 201
    r = await api_client.post("/api/v1/favorites", json={"sku": "A-2"})
    assert r.status_code == 201

    r = await api_client.get("/api/v1/favorites")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 2
    skus = {item["sku"] for item in body["data"]}
    assert skus == {"A-1", "A-2"}
    # актуальная цена присутствует
    assert body["data"][0]["client_price"] is not None

    r = await api_client.delete("/api/v1/favorites/A-1")
    assert r.status_code == 204
    assert (await api_client.get("/api/v1/favorites")).json()["meta"]["total"] == 1


async def test_add_idempotent(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    await api_client.post("/api/v1/favorites", json={"sku": "A-1"})
    r = await api_client.post("/api/v1/favorites", json={"sku": "A-1"})
    assert r.status_code == 201  # idempotent — не 409
    assert (await api_client.get("/api/v1/favorites")).json()["meta"]["total"] == 1


async def test_add_unknown_sku(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.post("/api/v1/favorites", json={"sku": "NOPE"})).status_code == 404


async def test_delete_missing(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.delete("/api/v1/favorites/A-1")).status_code == 404
