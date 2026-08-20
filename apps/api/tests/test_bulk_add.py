"""Тесты bulk-добавления (фича B, §16 п.20-5).

Покрытие:
  - POST /catalog/resolve-bulk: найден/не найден, цены под клиента (скидка),
    qty passthrough, дубликаты артикулов, лимит 1..500, авторизация
  - POST /cart/items/bulk: частичный успех, аккумулирование с существующей
    корзиной, все-отклонены → 200, валидация (qty=0 / пусто / >500), роли
"""

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
MANAGER_EMAIL = "manager@example.by"


async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _seed(sf):
    """Alpha: A-1 в наличии, A-2 под заказ, A-3 архив; NOPE — не существует."""
    brand = await create_brand(sf, name="Alpha")
    series = await create_series(sf, brand=brand, name="Serie X", photo_key="x.webp")
    p1 = await create_product(sf, sku="A-1", name="Widget", brand=brand,
                              series=series, base_price=100)
    p2 = await create_product(sf, sku="A-2", name="Gadget", brand=brand,
                              series=series, base_price=50,
                              stock=StockStatus.PREORDER)
    p3 = await create_product(sf, sku="A-3", name="Old thing", brand=brand,
                              series=series, base_price=70,
                              stock=StockStatus.ARCHIVED)
    return brand, p1, p2, p3


async def _seed_client(sf, brand=None):
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    if brand is not None:
        await set_discount(sf, user=user, brand=brand, percent=10)
    return user


# =========================================================
# POST /catalog/resolve-bulk
# =========================================================
async def test_resolve_bulk_requires_auth(api_client):
    r = await api_client.post(
        "/api/v1/catalog/resolve-bulk", json={"items": [{"sku": "A-1"}]}
    )
    assert r.status_code == 401


async def test_resolve_bulk_mixed(api_client, session_factory):
    sf = session_factory
    brand, _, _, _ = await _seed(sf)
    await _seed_client(sf, brand=brand)  # скидка 10% на бренд Alpha
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post(
        "/api/v1/catalog/resolve-bulk",
        json={
            "items": [
                {"sku": "A-1", "qty": 3},
                {"sku": "NOPE", "qty": 1},
                {"sku": "A-3"},          # архивный, но существует → found + цена
                {"sku": "A-1", "qty": 2},  # дубликат — отдельная строка результата
            ]
        },
    )
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 4

    by_sku = {}
    for row in rows:
        by_sku.setdefault(row["sku"], []).append(row)

    # найденный: имя, qty passthrough, персональная цена со скидкой
    a1 = by_sku["A-1"][0]
    assert a1["found"] is True
    assert a1["name"] == "Widget"
    assert a1["qty"] == 3
    assert a1["error"] is None
    assert a1["stock_status"] == "IN_STOCK"
    assert a1["price"]["base_price_byn"] == 100.0
    assert a1["price"]["client_price"] == 90.0  # 100 * (1 - 0.1)
    assert a1["price"]["retail_price"] == 100.0
    assert a1["price"]["has_discount"] is True
    assert a1["price"]["currency"] == "BYN"
    assert a1["price"]["rate_source"] == "BYN"

    # дубликат — своя строка со своим qty
    a1_dup = by_sku["A-1"][1]
    assert a1_dup["found"] is True
    assert a1_dup["qty"] == 2

    # не найденный
    nope = by_sku["NOPE"][0]
    assert nope["found"] is False
    assert nope["error"] == "Товар не найден"
    assert nope["name"] is None
    assert nope["price"] is None
    assert nope["stock_status"] is None

    # архивный товар разрешается (цена есть), статус — ARCHIVED
    a3 = by_sku["A-3"][0]
    assert a3["found"] is True
    assert a3["stock_status"] == "ARCHIVED"
    assert a3["price"]["client_price"] == 63.0  # 70 * (1 - 0.1)


async def test_resolve_bulk_manager_sees_retail(api_client, session_factory):
    """Менеджер без скидки видит client_price == рознице (price_product)."""
    sf = session_factory
    brand, _, _, _ = await _seed(sf)
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.post(
        "/api/v1/catalog/resolve-bulk", json={"items": [{"sku": "A-1", "qty": 1}]}
    )
    assert r.status_code == 200, r.text
    row = r.json()["data"][0]
    assert row["found"] is True
    assert row["price"]["client_price"] == 100.0
    assert row["price"]["has_discount"] is False


async def test_resolve_bulk_validation_limits(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await _seed_client(sf)
    await _login(api_client, CLIENT_EMAIL)

    # пустой список
    r = await api_client.post("/api/v1/catalog/resolve-bulk", json={"items": []})
    assert r.status_code == 422

    # больше 500 позиций
    r = await api_client.post(
        "/api/v1/catalog/resolve-bulk",
        json={"items": [{"sku": "A-1"}] * 501},
    )
    assert r.status_code == 422


# =========================================================
# POST /cart/items/bulk
# =========================================================
async def test_cart_bulk_requires_auth(api_client):
    r = await api_client.post(
        "/api/v1/cart/items/bulk", json={"items": [{"sku": "A-1", "qty": 1}]}
    )
    assert r.status_code == 401


async def test_cart_bulk_mixed_add_and_reject(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await _seed_client(sf)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post(
        "/api/v1/cart/items/bulk",
        json={
            "items": [
                {"sku": "A-1", "qty": 2},
                {"sku": "A-2", "qty": 1},   # PREORDER — добавляем
                {"sku": "A-3", "qty": 1},   # архив
                {"sku": "NOPE", "qty": 5},  # не найден
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == [
        {"sku": "A-1", "quantity": 2},
        {"sku": "A-2", "quantity": 1},
    ]
    assert body["rejected"] == [
        {"sku": "A-3", "reason": "Товар в архиве"},
        {"sku": "NOPE", "reason": "Товар не найден"},
    ]

    # проверка корзины через GET /cart
    r = await api_client.get("/api/v1/cart")
    assert r.status_code == 200
    cart = r.json()
    assert cart["total_items"] == 2
    quantities = {i["sku"]: i["quantity"] for i in cart["items"]}
    assert quantities == {"A-1": 2, "A-2": 1}
    assert cart["total_amount"] == 250.0  # 100*2 + 50*1 (скидки нет)


async def test_cart_bulk_accumulates(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await _seed_client(sf)
    await _login(api_client, CLIENT_EMAIL)

    # существующая позиция через одиночный POST /cart/items
    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 2})
    assert r.status_code == 201, r.text

    # bulk поверх неё + повтор того же артикула внутри одного запроса
    r = await api_client.post(
        "/api/v1/cart/items/bulk",
        json={"items": [{"sku": "A-1", "qty": 3}, {"sku": "A-1", "qty": 4}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # quantity — итоговое количество позиции (аккумуляция)
    assert body["added"] == [
        {"sku": "A-1", "quantity": 5},
        {"sku": "A-1", "quantity": 9},
    ]
    assert body["rejected"] == []

    r = await api_client.get("/api/v1/cart")
    cart = r.json()
    assert cart["total_items"] == 1
    assert cart["items"][0]["quantity"] == 9
    assert cart["total_amount"] == 900.0


async def test_cart_bulk_all_rejected_still_200(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await _seed_client(sf)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post(
        "/api/v1/cart/items/bulk",
        json={"items": [{"sku": "NOPE", "qty": 1}, {"sku": "A-3", "qty": 2}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == []
    assert body["rejected"] == [
        {"sku": "NOPE", "reason": "Товар не найден"},
        {"sku": "A-3", "reason": "Товар в архиве"},
    ]

    # корзина не изменилась
    r = await api_client.get("/api/v1/cart")
    assert r.json()["total_items"] == 0


async def test_cart_bulk_validation(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await _seed_client(sf)
    await _login(api_client, CLIENT_EMAIL)

    # qty = 0
    r = await api_client.post(
        "/api/v1/cart/items/bulk", json={"items": [{"sku": "A-1", "qty": 0}]}
    )
    assert r.status_code == 422

    # пустой список
    r = await api_client.post("/api/v1/cart/items/bulk", json={"items": []})
    assert r.status_code == 422

    # больше 500 позиций
    r = await api_client.post(
        "/api/v1/cart/items/bulk",
        json={"items": [{"sku": "A-1", "qty": 1}] * 501},
    )
    assert r.status_code == 422

    # ничего не добавлено
    r = await api_client.get("/api/v1/cart")
    assert r.json()["total_items"] == 0


async def test_cart_bulk_manager_allowed(api_client, session_factory):
    """POST /cart/items не ограничен ролью (get_current_user) — зеркалим."""
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.post(
        "/api/v1/cart/items/bulk", json={"items": [{"sku": "A-1", "qty": 1}]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == [{"sku": "A-1", "quantity": 1}]
