"""Тесты клиентского дашборда /api/v1/dashboard. См. §6, §16 п.20.

Слои:
  1. RBAC/скоуп: 401 без авторизации; данные строго в скоупе текущего
     клиента — чужие заявки не попадают ни в один блок ответа.
  2. GET /dashboard: KPI (без CANCELLED), график 30 дней с zero-fill,
     статусы, топ-5 товаров по количеству, последние/активные заявки,
     quick_actions.repeat_order_id.
  3. favorite_price_changes (price_history: down/up/new/без изменений) и
     new_arrivals.
  4. Кэш: в пределах TTL отдаётся закэшированный снимок, после сброса
     ключа — свежие данные (реальный Redis из docker-compose).
"""
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models.catalog import PriceHistory
from app.models.enums import OrderStatus, UserRole
from app.models.order import Order, OrderItem
from app.models.user import Favorite, User
from tests.conftest import create_product, create_user

PASSWORD = "Passw0rd!"
CLIENT_A_EMAIL = "client-a@example.by"
CLIENT_B_EMAIL = "client-b@example.by"
MSK = ZoneInfo("Europe/Minsk")


# ---------- helpers ----------

def _at_minsk(day: dt.date, hour: int = 12) -> dt.datetime:
    """Полдень (или ``hour``) указанного дня по Минску → UTC."""
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=MSK).astimezone(dt.timezone.utc)


async def _login(api_client, sf, email: str, *, role: UserRole = UserRole.CLIENT) -> User:
    user = await create_user(sf, email=email, role=role, password=PASSWORD)
    r = await api_client.post("/api/v1/auth/login",
                              json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return user


async def _order(sf, *, client, created_at, status=OrderStatus.NEW,
                 total=Decimal("0.00"), items=()) -> Order:
    async with sf() as s:
        order = Order(client_id=client.id, status=status, total_amount=total,
                      created_at=created_at)
        s.add(order)
        await s.flush()
        for product, qty, unit_price in items:
            s.add(OrderItem(order_id=order.id, product_id=product.id,
                            product_snapshot={"sku": product.sku, "name": product.name},
                            quantity=qty, unit_price=unit_price, created_at=created_at))
        await s.commit()
        await s.refresh(order)
        return order


async def _add_favorite(sf, *, user: User, product) -> None:
    async with sf() as s:
        s.add(Favorite(user_id=user.id, product_id=product.id))
        await s.commit()


# ------------------------------------------------------------- авторизация
async def test_dashboard_requires_auth(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_A_EMAIL, role=UserRole.CLIENT,
                      password=PASSWORD)
    r = await api_client.get("/api/v1/dashboard")
    assert r.status_code == 401


# ------------------------------------------------- скоуп и основной отчёт
async def test_dashboard_scoped_to_current_client(api_client, session_factory):
    sf = session_factory
    client_a = await _login(api_client, sf, CLIENT_A_EMAIL)
    client_b = await create_user(sf, email=CLIENT_B_EMAIL, role=UserRole.CLIENT,
                                 password=PASSWORD)

    today = dt.datetime.now(MSK).date()
    day3 = today - dt.timedelta(days=3)
    day10 = today - dt.timedelta(days=10)
    day35 = today - dt.timedelta(days=35)

    p1 = await create_product(sf, sku="P-1", name="Item One", base_price=Decimal("10.00"))
    p2 = await create_product(sf, sku="P-2", name="Item Two", base_price=Decimal("5.00"))

    o1 = await _order(sf, client=client_a, created_at=_at_minsk(today, 13),
                      total=Decimal("20.00"), items=[(p1, 2, Decimal("10.00"))])
    o2 = await _order(sf, client=client_a, created_at=_at_minsk(today, 11),
                      status=OrderStatus.CANCELLED, total=Decimal("1000.00"),
                      items=[(p2, 10, Decimal("5.00"))])
    o3 = await _order(sf, client=client_a, created_at=_at_minsk(day3),
                      status=OrderStatus.SHIPPED, total=Decimal("10.00"),
                      items=[(p1, 1, Decimal("10.00"))])
    o4 = await _order(sf, client=client_a, created_at=_at_minsk(day10),
                      status=OrderStatus.IN_PROGRESS, total=Decimal("0.00"))
    o5 = await _order(sf, client=client_a, created_at=_at_minsk(day35),
                      status=OrderStatus.COMPLETED, total=Decimal("5.00"))
    # Чужая заявка: не должна просочиться ни в один блок.
    foreign = await _order(sf, client=client_b, created_at=_at_minsk(today),
                           total=Decimal("999.00"), items=[(p2, 100, Decimal("5.00"))])

    # Заказы на границе месяца могут не попасть в «текущий месяц» — считаем
    # ожидания по тому же правилу (дата Минска >= первого числа).
    month_start = today.replace(day=1)
    o3_in_month = day3 >= month_start
    o4_in_month = day10 >= month_start

    r = await api_client.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()

    # --- KPI: без CANCELLED, только свои
    kpi = body["kpi"]
    assert kpi["orders_total"] == 4                     # o1, o3, o4, o5
    assert kpi["orders_this_month"] == 1 + (1 if o3_in_month else 0) + (1 if o4_in_month else 0)
    assert Decimal(kpi["total_spent_byn"]) == Decimal("35")
    assert Decimal(kpi["avg_order_byn"]) == Decimal("8.75")   # 35 / 4

    # --- orders_by_day: ровно 30 дней, по возрастанию, zero-fill
    chart = body["orders_by_day"]
    expected_days = [today - dt.timedelta(days=back) for back in range(29, -1, -1)]
    assert [row["date"] for row in chart] == [d.isoformat() for d in expected_days]
    by_date = {row["date"]: row["count"] for row in chart}
    assert by_date[today.isoformat()] == 2              # o1+o2 (любой статус; чужая не считается)
    assert by_date[day3.isoformat()] == 1
    assert by_date[day10.isoformat()] == 1
    assert day35.isoformat() not in by_date

    # --- status_counts: все статусы клиента, чужих нет
    statuses = {row["status"]: row["count"] for row in body["status_counts"]}
    assert statuses == {
        "NEW": 1, "CANCELLED": 1, "SHIPPED": 1, "IN_PROGRESS": 1, "COMPLETED": 1,
    }

    # --- top_products: по количеству, CANCELLED исключён
    top_products = body["top_products"]
    assert len(top_products) == 1
    assert top_products[0]["product_id"] == str(p1.id)
    assert top_products[0]["sku"] == "P-1"
    assert top_products[0]["qty"] == 3                  # 2 + 1
    assert Decimal(top_products[0]["revenue_byn"]) == Decimal("30")

    # --- recent_orders: 5 последних (любой статус), новые раньше
    recent = body["recent_orders"]
    assert [row["id"] for row in recent] == [str(o.id) for o in (o1, o2, o3, o4, o5)]
    assert recent[0]["status"] == "NEW"
    assert Decimal(recent[0]["total_amount"]) == Decimal("20")
    assert all(row["id"] != str(foreign.id) for row in recent)

    # --- active_orders: NEW/IN_PROGRESS, номер форматируется бэкендом
    active = body["active_orders"]
    assert [row["id"] for row in active] == [str(o1.id), str(o4.id)]
    assert active[0]["number"] == f"№{str(o1.id)[:8]}"
    assert active[1]["status"] == "IN_PROGRESS"

    # --- quick_actions: повторять — последняя своя заявка
    assert body["quick_actions"]["repeat_order_id"] == str(o1.id)


# ------------------------- цены избранного и новинки (без заявок тоже работает)
async def test_dashboard_favorite_price_changes_and_new_arrivals(api_client, session_factory):
    sf = session_factory
    client = await _login(api_client, sf, CLIENT_A_EMAIL)

    now = dt.datetime.now(dt.timezone.utc)
    # Цена упала 120 → 100: категория «down».
    p_down = await create_product(sf, sku="F-DOWN", name="Down", base_price=Decimal("100.00"))
    # Одна запись истории: категория «new».
    p_new = await create_product(sf, sku="F-NEW", name="New", base_price=Decimal("50.00"))
    # История есть, цена не менялась: пропускается.
    p_same = await create_product(sf, sku="F-SAME", name="Same", base_price=Decimal("50.00"))

    async with sf() as s:
        s.add_all([
            PriceHistory(product_id=p_down.id, base_price=Decimal("120.00"),
                         changed_at=now - dt.timedelta(days=2)),
            PriceHistory(product_id=p_down.id, base_price=Decimal("100.00"),
                         changed_at=now - dt.timedelta(days=1)),
            PriceHistory(product_id=p_new.id, base_price=Decimal("50.00"),
                         changed_at=now - dt.timedelta(days=1)),
            PriceHistory(product_id=p_same.id, base_price=Decimal("50.00"),
                         changed_at=now - dt.timedelta(days=2)),
            PriceHistory(product_id=p_same.id, base_price=Decimal("50.00"),
                         changed_at=now - dt.timedelta(days=1)),
        ])
        await s.commit()

    await _add_favorite(sf, user=client, product=p_down)
    await _add_favorite(sf, user=client, product=p_new)
    await _add_favorite(sf, user=client, product=p_same)

    r = await api_client.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()

    changes = {row["sku"]: row for row in body["favorite_price_changes"]}
    assert set(changes) == {"F-DOWN", "F-NEW"}          # F-SAME без изменений

    down = changes["F-DOWN"]
    assert down["category"] == "down"
    assert Decimal(down["new_client_price"]) == Decimal("100")
    assert Decimal(down["old_client_price"]) == Decimal("120")
    assert Decimal(down["delta_percent"]) == Decimal("-16.67")
    assert down["currency"] == "BYN"

    new = changes["F-NEW"]
    assert new["category"] == "new"
    assert new["old_client_price"] is None
    assert new["delta_percent"] is None

    # new_arrivals: последние не удалённые товары с клиентской ценой
    arrivals = {row["sku"]: row for row in body["new_arrivals"]}
    assert {"F-DOWN", "F-NEW", "F-SAME"} <= set(arrivals)
    assert all(row["currency"] == "BYN" for row in arrivals.values())
    assert all("client_price" in row for row in arrivals.values())


# -------------------------------------------------------------------- кэш
async def test_dashboard_cached_until_key_reset(api_client, session_factory):
    """В пределах TTL эндпоинт отдаёт закэшированный снимок; сброс ключа
    возвращает свежие данные (персональный ключ клиента)."""
    sf = session_factory
    client = await _login(api_client, sf, CLIENT_A_EMAIL)
    today = dt.datetime.now(MSK).date()
    await _order(sf, client=client, created_at=_at_minsk(today))

    r1 = await api_client.get("/api/v1/dashboard")
    assert r1.status_code == 200, r1.text
    assert r1.json()["kpi"]["orders_total"] == 1

    # Заказ после первого запроса — в пределах TTL не виден (кэш).
    await _order(sf, client=client, created_at=_at_minsk(today, 13))
    r2 = await api_client.get("/api/v1/dashboard")
    assert r2.status_code == 200, r2.text
    assert r2.json()["kpi"]["orders_total"] == 1

    from app.services import cache as cache_module

    await cache_module.cache.redis.delete(
        cache_module.cache.data_key(f"client:dashboard:v1:{client.id}")
    )
    r3 = await api_client.get("/api/v1/dashboard")
    assert r3.status_code == 200, r3.text
    assert r3.json()["kpi"]["orders_total"] == 2


# --------------------------------------------- пустая БД — нули, не падаем
async def test_dashboard_empty_state(api_client, session_factory):
    await _login(api_client, session_factory, CLIENT_A_EMAIL)
    r = await api_client.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"] == {
        "orders_total": 0,
        "orders_this_month": 0,
        "total_spent_byn": "0",
        "avg_order_byn": "0.00",
    }
    assert len(body["orders_by_day"]) == 30
    assert all(row["count"] == 0 for row in body["orders_by_day"])
    assert body["status_counts"] == []
    assert body["top_products"] == []
    assert body["recent_orders"] == []
    assert body["active_orders"] == []
    assert body["favorite_price_changes"] == []
    assert body["new_arrivals"] == []
    assert body["quick_actions"]["repeat_order_id"] is None
