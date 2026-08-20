"""Тесты дашборда менеджера (фича G). См. §6, §16 п.20-1.

Слои:
  1. GET /manager/dashboard: KPI (заказы сегодня/7д, выручка месяца без
     CANCELLED, новые клиенты 7д, активные импорты), график 30 дней с
     zero-fill по возрастанию, топы товаров/клиентов, последние заявки.
  2. Кэш: в пределах TTL отдаётся закэшированный снимок, после сброса
     ключа — свежие данные (реальный Redis из docker-compose).
"""
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.security import hash_password
from app.models.catalog import PriceListVersion
from app.models.enums import OrderStatus, PriceListVersionStatus, UserRole
from app.models.order import Order, OrderItem
from app.models.user import User
from tests.conftest import create_product, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"
MSK = ZoneInfo("Europe/Minsk")


# ---------- helpers ----------

def _at_minsk(day: dt.date, hour: int = 12) -> dt.datetime:
    """Полдень (или ``hour``) указанного дня по Минску → UTC.

    Детерминированно вне зависимости от времени запуска теста.
    """
    return dt.datetime.combine(day, dt.time(hour, 0), tzinfo=MSK).astimezone(dt.timezone.utc)


async def _client_at(sf, email: str, created_at: dt.datetime, *, company=None) -> User:
    async with sf() as s:
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            full_name=email.split("@")[0].title(),
            company=company,
            role=UserRole.CLIENT,
            is_active=True,
            created_at=created_at,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
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


async def _login_manager(api_client, sf):
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER,
                                password=PASSWORD)
    r = await api_client.post("/api/v1/auth/login",
                              json={"email": MANAGER_EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return manager


# ------------------------------------------------------------------- RBAC
async def test_dashboard_requires_manager_role(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT,
                      password=PASSWORD)
    r = await api_client.post("/api/v1/auth/login",
                              json={"email": CLIENT_EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert (await api_client.get("/api/v1/manager/dashboard")).status_code == 403


# ------------------------------------------------------------ основной отчёт
async def test_dashboard_kpi_charts_and_tops(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)

    today = dt.datetime.now(MSK).date()
    day3 = today - dt.timedelta(days=3)
    day10 = today - dt.timedelta(days=10)
    day35 = today - dt.timedelta(days=35)

    client_a = await _client_at(sf, "a@x.by", _at_minsk(today), company="ООО Альфа")
    client_b = await _client_at(sf, "b@x.by", _at_minsk(today))
    await _client_at(sf, "c@x.by", _at_minsk(day3))    # новый клиент (3 дня назад)
    await _client_at(sf, "d@x.by", _at_minsk(day35))   # старый — не попадает в 7д

    p1 = await create_product(sf, sku="P-1", name="Item One", base_price=Decimal("10.00"))
    p2 = await create_product(sf, sku="P-2", name="Item Two", base_price=Decimal("5.00"))
    p3 = await create_product(sf, sku="P-3", name="Item Three", base_price=Decimal("100.00"))

    o1 = await _order(sf, client=client_a, created_at=_at_minsk(today, 13),
                      total=Decimal("20.00"), items=[(p1, 2, Decimal("10.00"))])
    o2 = await _order(sf, client=client_b, created_at=_at_minsk(today, 11),
                      total=Decimal("5.00"), items=[(p2, 1, Decimal("5.00"))])
    o3 = await _order(sf, client=client_a, created_at=_at_minsk(today, 10),
                      status=OrderStatus.CANCELLED, total=Decimal("1000.00"),
                      items=[(p3, 10, Decimal("100.00"))])
    o4 = await _order(sf, client=client_b, created_at=_at_minsk(day3),
                      total=Decimal("10.00"), items=[(p1, 1, Decimal("10.00"))])
    o5 = await _order(sf, client=client_a, created_at=_at_minsk(day10),
                      total=Decimal("0.00"))
    await _order(sf, client=client_a, created_at=_at_minsk(day35))  # вне окна 30 дней

    async with sf() as s:
        s.add(PriceListVersion(uploaded_by=manager.id, filename="price.csv",
                               status=PriceListVersionStatus.QUEUED))
        s.add(PriceListVersion(uploaded_by=manager.id, filename="done.csv",
                               status=PriceListVersionStatus.DONE))
        await s.commit()

    # Заказы на границе месяца могут не попасть в «текущий месяц» — считаем
    # ожидания по тому же правилу (дата Минска >= первого числа).
    month_start = today.replace(day=1)
    o4_in_month = day3 >= month_start
    o5_in_month = day10 >= month_start

    r = await api_client.get("/api/v1/manager/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()

    # --- KPI
    kpi = body["kpi"]
    assert kpi["orders_today"] == 3                     # o1+o2+o3 (любой статус)
    assert kpi["orders_7d"] == 4                        # o1..o4
    expected_revenue = Decimal("25") + (Decimal("10") if o4_in_month else 0)
    assert Decimal(kpi["revenue_month"]) == expected_revenue
    assert kpi["new_clients_7d"] == 3                   # a, b, c (d — 35 дней назад)
    assert kpi["active_imports"] == 1                   # QUEUED; DONE не в счёте

    # --- orders_by_day: ровно 30 дней, по возрастанию, zero-fill
    chart = body["orders_by_day"]
    expected_days = [today - dt.timedelta(days=back) for back in range(29, -1, -1)]
    assert [row["date"] for row in chart] == [d.isoformat() for d in expected_days]
    by_date = {row["date"]: row["count"] for row in chart}
    assert by_date[today.isoformat()] == 3
    assert by_date[day3.isoformat()] == 1
    assert by_date[day10.isoformat()] == 1
    assert sum(1 for v in by_date.values() if v == 0) == 27
    assert day35.isoformat() not in by_date

    # --- top_products: по выручке месяца, CANCELLED исключён
    top_products = body["top_products"]
    assert top_products[0]["product_id"] == str(p1.id)
    assert top_products[0]["sku"] == "P-1"
    assert top_products[0]["qty"] == (3 if o4_in_month else 2)
    assert Decimal(top_products[0]["revenue"]) == (Decimal("30") if o4_in_month
                                                   else Decimal("20"))
    assert top_products[1]["sku"] == "P-2"
    assert Decimal(top_products[1]["revenue"]) == Decimal("5")
    assert all(tp["sku"] != "P-3" for tp in top_products)

    # --- top_clients: компания приоритетнее ФИО
    top_clients = body["top_clients"]
    assert top_clients[0]["client_id"] == str(client_a.id)
    assert top_clients[0]["name"] == "ООО Альфа"
    assert Decimal(top_clients[0]["revenue"]) == Decimal("20")
    assert top_clients[0]["orders"] == 1 + (1 if o5_in_month else 0)
    assert top_clients[1]["client_id"] == str(client_b.id)
    assert top_clients[1]["name"] == "B"                # нет компании → full_name
    assert Decimal(top_clients[1]["revenue"]) == (Decimal("15") if o4_in_month
                                                  else Decimal("5"))
    assert top_clients[1]["orders"] == (2 if o4_in_month else 1)

    # --- recent_orders: 5 последних, новые раньше
    recent = body["recent_orders"]
    assert len(recent) == 5
    assert [row["id"] for row in recent] == [str(o.id) for o in (o1, o2, o3, o4, o5)]
    assert recent[0]["client_name"] == "ООО Альфа"
    assert recent[0]["status"] == "NEW"
    assert Decimal(recent[0]["total_amount"]) == Decimal("20")


# -------------------------------------------------------------------- кэш
async def test_dashboard_cached_until_key_reset(api_client, session_factory):
    """В пределах TTL эндпоинт отдаёт закэшированный снимок; сброс ключа
    (или теговая инвалидация) возвращает свежие данные."""
    sf = session_factory
    await _login_manager(api_client, sf)
    today = dt.datetime.now(MSK).date()
    client = await _client_at(sf, "a@x.by", _at_minsk(today))
    now = dt.datetime.now(dt.timezone.utc)
    await _order(sf, client=client, created_at=now)

    r1 = await api_client.get("/api/v1/manager/dashboard")
    assert r1.status_code == 200, r1.text
    assert r1.json()["kpi"]["orders_today"] == 1

    # Заказ после первого запроса — в пределах TTL не виден (кэш).
    await _order(sf, client=client, created_at=now)
    r2 = await api_client.get("/api/v1/manager/dashboard")
    assert r2.status_code == 200, r2.text
    assert r2.json()["kpi"]["orders_today"] == 1

    from app.services import cache as cache_module

    await cache_module.cache.redis.delete(
        cache_module.cache.data_key("manager:dashboard:v1")
    )
    r3 = await api_client.get("/api/v1/manager/dashboard")
    assert r3.status_code == 200, r3.text
    assert r3.json()["kpi"]["orders_today"] == 2


# --------------------------------------------- пустая БД — нули, не падаем
async def test_dashboard_empty_state(api_client, session_factory):
    await _login_manager(api_client, session_factory)
    r = await api_client.get("/api/v1/manager/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"] == {
        "orders_today": 0,
        "orders_7d": 0,
        "revenue_month": "0",
        "new_clients_7d": 0,
        "active_imports": 0,
    }
    assert len(body["orders_by_day"]) == 30
    assert all(row["count"] == 0 for row in body["orders_by_day"])
    assert body["top_products"] == []
    assert body["top_clients"] == []
    assert body["recent_orders"] == []

    # кроме дашборда, в БД нет заказов и клиентов
    async with session_factory() as s:
        assert (await s.scalar(select(Order.id))) is None
        assert (await s.scalar(select(User.id).where(User.role == UserRole.CLIENT))) is None
