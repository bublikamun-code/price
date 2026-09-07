"""Тесты корзины (persist в БД). См. §19, §6 (/cart)."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.enums import StockStatus, UserRole
from app.models.order import Cart
from app.repositories import cart as cart_repo
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


# =========================================================
# UNIQUE carts.user_id (аудит 2026-09-06: две корзины одному клиенту)
# =========================================================
async def test_second_cart_same_user_integrity_error(session_factory):
    """Вторая корзина того же пользователя невозможна: uq_carts_user_id."""
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    async with sf() as s:
        s.add(Cart(user_id=user.id))
        await s.commit()
        s.add(Cart(user_id=user.id))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_get_or_create_cart_returns_existing(session_factory):
    """get_or_create не плодит дубли: существующая корзина возвращается как есть."""
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    async with sf() as s:
        created = await cart_repo.get_or_create_cart(s, user_id=user.id)
        await s.commit()
    async with sf() as s:
        again = await cart_repo.get_or_create_cart(s, user_id=user.id)
        assert again.id == created.id


async def test_concurrent_cart_add_creates_single_cart(api_client, session_factory):
    """Гонка get_or_create (check-then-insert): два параллельных добавления
    в несуществующую корзину → обе операции успешны, корзина одна.

    Проигравшая вставка получает IntegrityError от uq_carts_user_id и
    восстанавливается через SAVEPOINT + перечитывание (репозиторий).
    """
    sf = session_factory
    await _seed(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    async def _add():
        return await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 1})

    r1, r2 = await asyncio.gather(_add(), _add())
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    # Обе операции работали с одной и той же корзиной.
    assert r1.json()["id"] == r2.json()["id"]

    async with sf() as s:
        carts = (
            (await s.execute(select(Cart).where(Cart.user_id == user.id))).scalars().all()
        )
        assert len(carts) == 1


# =========================================================
# Батч-цены в view (аудит 2026-09-06: N+1) — семантика §8 сохранена
# =========================================================
async def test_view_batch_prices_mixed_brands(api_client, session_factory):
    """Два бренда, скидка заведена на один: батч-расчёт даёт цены §8 по каждой позиции."""
    sf = session_factory
    brand_a = await create_brand(sf, name="Alpha")
    brand_b = await create_brand(sf, name="Beta")
    await create_product(sf, sku="A-1", name="Widget", brand=brand_a, base_price=100)
    await create_product(sf, sku="B-1", name="Gadget", brand=brand_b, base_price=50)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand_a, percent=10)
    await _login(api_client, CLIENT_EMAIL)

    await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 2})
    r = await api_client.post("/api/v1/cart/items", json={"sku": "B-1", "quantity": 1})
    assert r.status_code == 201, r.text

    by_sku = {i["sku"]: i for i in r.json()["items"]}
    assert by_sku["A-1"]["unit_price"] == 90.0  # 100 * (1 - 0.1) — со скидкой
    assert by_sku["B-1"]["unit_price"] == 50.0  # без скидки
    assert r.json()["total_amount"] == 230.0
