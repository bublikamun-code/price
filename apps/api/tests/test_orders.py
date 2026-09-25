"""Тесты заявок клиента. См. §6, §9, §17.2 (снапшот цен/курса).

Ключевая проверка: цена и курс замораживаются при оформлении и НЕ
пересчитываются при последующих изменениях прайса/скидки/курса.
"""
import asyncio
import uuid

from sqlalchemy import select

from app.models.catalog import Product
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
        "items": [{"sku": "A-1", "quantity": 3}], "notes": "срочно",
        "delivery_point": "Склад Минск"
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
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-2", "quantity": 1}], "delivery_point": "Склад Минск"})
    assert r.status_code == 400
    assert r.headers["X-Error-Code"] == "PRODUCT_UNAVAILABLE"


async def test_create_unknown_sku(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "NOPE", "quantity": 1}], "delivery_point": "Склад Минск"})
    assert r.status_code == 404
    assert r.headers["X-Error-Code"] == "PRODUCT_NOT_FOUND"


async def test_create_order_idempotency_replays_same_result(api_client, session_factory):
    """Повтор с тем же ключом и payload не создаёт вторую заявку."""
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    payload = {
        "items": [{"sku": "A-1", "quantity": 1}],
        "delivery_point": "Склад Минск",
    }

    first = await api_client.post(
        "/api/v1/orders", json=payload, headers={"Idempotency-Key": "submit-001"}
    )
    second = await api_client.post(
        "/api/v1/orders", json=payload, headers={"Idempotency-Key": "submit-001"}
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.headers["X-Idempotency-Replayed"] == "false"
    assert second.headers["X-Idempotency-Replayed"] == "true"
    assert second.json()["total_amount"] == first.json()["total_amount"]


async def test_create_order_idempotency_rejects_changed_payload(api_client, session_factory):
    """Тот же ключ с другим payload даёт стабильный конфликт."""
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    base = {
        "items": [{"sku": "A-1", "quantity": 1}],
        "delivery_point": "Склад Минск",
    }
    first = await api_client.post(
        "/api/v1/orders", json=base, headers={"Idempotency-Key": "submit-002"}
    )
    changed = await api_client.post(
        "/api/v1/orders",
        json={**base, "items": [{"sku": "A-1", "quantity": 2}]},
        headers={"Idempotency-Key": "submit-002"},
    )

    assert first.status_code == 201, first.text
    assert changed.status_code == 409
    assert changed.headers["X-Error-Code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_create_order_with_structured_delivery(api_client, session_factory):
    """Структурированная доставка сохраняется отдельными полями заказа."""
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post(
        "/api/v1/orders",
        json={
            "items": [{"sku": "A-1", "quantity": 1}],
            "delivery": {
                "method": "DELIVERY",
                "address": "Минск, ул. Примерная, 1",
                "contact_name": "Иван",
                "phone": "+375291234567",
                "preferred_date": "2026-10-02",
                "comment": "После 14:00",
            },
        },
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["delivery_method"] == "delivery"
    assert order["delivery_address"] == "Минск, ул. Примерная, 1"
    assert order["delivery_contact_name"] == "Иван"
    assert order["delivery_phone"] == "+375291234567"
    assert order["delivery_preferred_date"] == "2026-10-02"
    assert order["delivery_comment"] == "После 14:00"


# =========================================================
# SEQ — сквозные номера без дублей (аудит 2026-09-06: гонка MAX(seq)+1)
# =========================================================
async def test_order_seq_assigned_and_unique(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    for _ in range(3):
        r = await api_client.post("/api/v1/orders", json={
            "items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"
        })
        assert r.status_code == 201, r.text

    async with sf() as s:
        seqs = (await s.execute(select(Order.seq))).scalars().all()
    assert all(sq is not None for sq in seqs)
    assert len(set(seqs)) == 3  # без дублей
    assert sorted(seqs) == list(range(min(seqs), min(seqs) + 3))  # монотонно, шаг 1


async def test_concurrent_orders_get_distinct_seq(api_client, session_factory):
    """Два параллельных оформления: nextval выдаёт разные номера, обе заявки 201.

    FOR UPDATE на строках товаров сериализует оформления: второй запрос ждёт
    коммит первого и получает следующий nextval (раньше — uq_orders_seq → 500).
    """
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    async def _create():
        return await api_client.post("/api/v1/orders", json={
            "items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"
        })

    r1, r2 = await asyncio.gather(_create(), _create())
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] != r2.json()["id"]

    async with sf() as s:
        seqs = (await s.execute(select(Order.seq))).scalars().all()
    assert len(seqs) == 2
    assert len(set(seqs)) == 2


# =========================================================
# OVERSELL — остатки при заказе (аудит 2026-09-06)
# =========================================================
async def test_order_exceeds_stock_returns_422(api_client, session_factory):
    """Заказ больше остатка (stock_qty IS NOT NULL) → 422 StockExceededError."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="S-1", name="Widget", brand=brand, base_price=10, stock_qty=5)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [{"sku": "S-1", "quantity": 6}], "delivery_point": "Склад Минск"
    })
    assert r.status_code == 422
    assert "S-1" in r.json()["detail"]


async def test_duplicate_order_lines_are_aggregated_before_stock_validation(api_client, session_factory):
    """Две строки одного SKU не обходят проверку остатка суммарной quantity."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="S-DUP", name="Widget", brand=brand, base_price=10, stock_qty=10)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [
            {"sku": "S-DUP", "quantity": 6},
            {"sku": "S-DUP", "quantity": 6},
        ],
        "delivery_point": "Склад Минск",
    })
    assert r.status_code == 422
    assert "S-DUP" in r.json()["detail"]


async def test_duplicate_order_lines_are_merged_into_one_item(api_client, session_factory):
    """В совместимом v1 payload дубли агрегируются, а не создают две позиции."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="S-MERGE", name="Widget", brand=brand, base_price=10, stock_qty=20)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [
            {"sku": "S-MERGE", "quantity": 2, "note": "первая"},
            {"sku": "S-MERGE", "quantity": 3, "note": "вторая"},
        ],
        "delivery_point": "Склад Минск",
    })
    assert r.status_code == 201, r.text
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["quantity"] == 5
    assert r.json()["items"][0]["note"] == "первая\nвторая"


async def test_order_with_null_stock_not_limited(api_client, session_factory):
    """stock_qty IS NULL → остаток не отслеживается, заказ любой quantity проходит."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="S-2", name="Widget", brand=brand, base_price=10, stock_qty=None)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={
        "items": [{"sku": "S-2", "quantity": 1000}], "delivery_point": "Склад Минск"
    })
    assert r.status_code == 201, r.text


async def test_second_order_on_last_unit_fails(api_client, session_factory):
    """Последняя единица: после коммита изменения остатка (эффект транзакции,
    владевшей блокировкой FOR UPDATE) второй заказ на то же количество → 422.

    FOR UPDATE в create() сериализует оформления: конкурентная заявка видит
    закоммиченный остаток, а не снимок, прочитанный до блокировки.
    """
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    p = await create_product(sf, sku="S-3", name="Widget", brand=brand, base_price=10, stock_qty=1)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    payload = {"items": [{"sku": "S-3", "quantity": 1}], "delivery_point": "Склад Минск"}
    r1 = await api_client.post("/api/v1/orders", json=payload)
    assert r1.status_code == 201, r1.text

    # Эффект параллельной транзакции, державшей блокировку строки (импорт
    # прайса / патч менеджера уменьшили остаток и закоммитились).
    async with sf() as s:
        prod = await s.get(Product, p.id)
        prod.stock_qty = 0
        await s.commit()

    r2 = await api_client.post("/api/v1/orders", json=payload)
    assert r2.status_code == 422
    assert "S-3" in r2.json()["detail"]


# =========================================================
# SNAPSHOT — цена замораживается
# =========================================================
async def test_price_snapshot_freezes_after_price_change(api_client, session_factory):
    sf = session_factory
    brand, p1, _ = await _seed(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand, percent=10)  # клиентская цена = 90
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})
    assert r.status_code == 201
    order_id = r.json()["id"]
    frozen_unit_price = r.json()["items"][0]["unit_price"]
    assert frozen_unit_price == 90.0

    # Меняем прайс и убираем скидку ПОСЛЕ оформления.
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
        "items": [{"sku": "A-1", "quantity": 2}], "price_calc_mode": "fixed",
        "delivery_point": "Склад Минск"
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
    await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})

    await _login(api_client, OTHER_EMAIL)
    await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 2}], "delivery_point": "Склад Минск"})

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
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})).json()["id"]

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
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})).json()["id"]

    r = await api_client.post(f"/api/v1/orders/{order_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


async def test_cancel_completed_conflict(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})).json()["id"]

    # Симулируем завершённый статус напрямую в БД (менеджер довёл до COMPLETED).
    async with sf() as s:
        order = await s.get(Order, uuid.UUID(order_id))
        order.status = OrderStatus.COMPLETED
        await s.commit()

    r = await api_client.post(f"/api/v1/orders/{order_id}/cancel")
    assert r.status_code == 409
    assert r.headers["X-Error-Code"] == "ORDER_NOT_CANCELABLE"


# =========================================================
# CART CLEARED AFTER ORDER CREATE
# =========================================================
async def test_cart_cleared_after_order_create(api_client, session_factory):
    """После оформления заявки корзина должна быть пуста (очищается атомарно на бэке)."""
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    # Добавляем товар в корзину
    r = await api_client.post("/api/v1/cart/items", json={"sku": "A-1", "quantity": 2})
    assert r.status_code == 201
    assert r.json()["total_items"] == 1

    # Оформляем заявку
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 2}], "delivery_point": "Склад Минск"})
    assert r.status_code == 201

    # Корзина должна быть пуста
    r = await api_client.get("/api/v1/cart")
    assert r.status_code == 200
    assert r.json()["total_items"] == 0


# =========================================================
# REPEAT (фича C)
# =========================================================
async def test_repeat_order_fills_cart(api_client, session_factory):
    sf = session_factory
    await _seed(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    order_id = (await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 4}], "delivery_point": "Склад Минск"})).json()["id"]

    r = await api_client.post(f"/api/v1/orders/{order_id}/repeat")
    assert r.status_code == 200, r.text
    cart = r.json()
    assert cart["total_items"] == 1
    assert cart["items"][0]["sku"] == "A-1"
    assert cart["items"][0]["quantity"] == 4
