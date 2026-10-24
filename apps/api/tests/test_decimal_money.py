"""Денежная арифметика на Decimal: точность, округление, смешение с курсом.

Регресс на класс ошибок из §8/§17: колонки объявлены ``Numeric(...)``, значит
драйвер отдаёт ``Decimal``, а код местами типизировал их как ``float`` и
считал в ``round()``. Итог — либо ``TypeError`` (``Decimal + float``), либо
тихая потеря копейки (округление банкерским правилом вместо HALF_UP).

Что проверяем:
  * округление денег HALF_UP (0.005 → 0.01; 2.005 → 2.01, где banker's дал бы
    2.00) и курса — до четырёх знаков;
  * точность сложения цен (корзина/заявка), без накопления float-хвоста;
  * отсутствие ``TypeError`` при смешении денег с курсом валюты (Decimal-курс
    из ``exchange_rates.rate``, а не float);
  * ORM отдаёт ``Decimal`` во всех денежных колонках, а JSON-контракт v1
    остался прежним — числа, не строки.
"""
import json
from decimal import Decimal

from sqlalchemy import select

from app.models.catalog import Product
from app.models.enums import UserRole
from app.models.order import Order, OrderItem
from app.models.pricing import ExchangeRate, UserBrand
from app.services.pricing import (
    _cache_safe_ladder,
    client_price_byn,
    convert_to_currency,
    quantize_money,
    quantize_rate,
    volume_tier_ladder,
)
from tests.conftest import (
    create_brand,
    create_product,
    create_user,
    set_discount,
    set_fixed_rate_for_user,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"


async def _login(api_client, email=CLIENT_EMAIL):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


# =========================================================
# Чистые функции: округление
# =========================================================
def test_quantize_money_half_up_on_half_kopeck():
    """Полу-копейка округляется вверх (HALF_UP), а не к «чётному» числу."""
    assert quantize_money(Decimal("0.005")) == Decimal("0.01")
    assert quantize_money(Decimal("2.005")) == Decimal("2.01")  # banker's → 2.00
    assert quantize_money(Decimal("2.015")) == Decimal("2.02")  # banker's → 2.02
    assert quantize_money(Decimal("-0.005")) == Decimal("-0.01")


def test_quantize_money_below_half_kopeck_is_down():
    assert quantize_money(Decimal("0.004")) == Decimal("0.00")
    assert quantize_money(Decimal("1.0049999")) == Decimal("1.00")


def test_quantize_money_accepts_db_and_str_values():
    """В БД приходит Decimal, из HTTP/CSV — строка: оба идут точно."""
    assert quantize_money(Decimal("12.345")) == Decimal("12.35")
    assert quantize_money("12,345".replace(",", ".")) == Decimal("12.35")
    assert quantize_money(10) == Decimal("10.00")


def test_quantize_money_is_exact_for_third_of_cent():
    """1/3 копейки накапливался во float; Decimal хранит точный остаток."""
    third = Decimal("0.01") / Decimal(3)
    assert quantize_money(third) == Decimal("0.00")
    assert quantize_money(third) * 3 == Decimal("0.00")


def test_quantize_rate_four_places_half_up():
    """Курс — точность колонки Numeric(12, 4), округление там же HALF_UP."""
    assert quantize_rate(Decimal("3.12345")) == Decimal("3.1235")
    assert quantize_rate(Decimal("3")) == Decimal("3.0000")
    assert quantize_rate("0.00005") == Decimal("0.0001")


def test_quantize_rejects_none():
    for fn in (quantize_money, quantize_rate):
        try:
            fn(None)
        except ValueError:
            continue
        raise AssertionError(f"{fn.__name__}(None) должен падать")


# =========================================================
# Чистые функции: точность и смешение с курсом
# =========================================================
def test_money_sum_has_no_float_tail():
    """Сумма цен — ровно то, что сложили; float давал 0.30000000000000004."""
    prices = [Decimal("0.10"), Decimal("0.20"), Decimal("0.05")]
    total = Decimal(0)
    for price in prices:
        total += quantize_money(price)
    assert total == Decimal("0.35")
    assert quantize_money(total) == Decimal("0.35")


def test_discounted_price_rounds_half_up_not_bankers():
    """4.01 − 50% = 2.005: HALF_UP → 2.01 (float+round давал 2.0)."""
    assert client_price_byn(
        base_price=Decimal("4.01"), override_price=None, discount_percent=Decimal("50")
    ) == Decimal("2.01")


def test_decimal_money_mixes_with_currency_rate_without_typeerror():
    """Decimal-цена + Decimal-курс: ни TypeError, ни потери знаков."""
    amount = Decimal("100.00")
    rate = Decimal("3.1234")
    converted = convert_to_currency(amount, rate, 1)
    assert isinstance(converted, Decimal)
    assert converted == Decimal("32.02")  # 100 / 3.1234 = 32.0164... → HALF_UP

    # Курс округляется под точность колонки, но не «съедает» копейки суммы.
    assert quantize_rate(rate) + amount == Decimal("103.1234")
    assert quantize_money(converted * 3) == Decimal("96.06")


def test_convert_with_rub_scale_stays_decimal():
    got = convert_to_currency(Decimal("100.00"), Decimal("3.5"), 100)
    assert got == Decimal("2857.14")
    assert isinstance(got, Decimal)


# =========================================================
# Лестница скидок: Decimal → JSON → Decimal без потери знаков
# =========================================================
class _Tier:
    def __init__(self, min_qty: int, discount_percent) -> None:
        self.min_qty = min_qty
        self.discount_percent = discount_percent


def test_volume_tier_ladder_is_decimal():
    ladder = volume_tier_ladder([_Tier(10, Decimal("2.50")), _Tier(50, Decimal("7"))])
    assert [tier["discount_percent"] for tier in ladder] == [
        Decimal("2.50"),
        Decimal("7"),
    ]
    assert all(isinstance(t["discount_percent"], Decimal) for t in ladder)


def test_volume_tier_ladder_survives_cache_roundtrip():
    """Redis — JSON без decimal: кэшируем строкой, читаем без потери знаков."""
    ladder = volume_tier_ladder([_Tier(10, Decimal("2.50"))])
    cached = json.loads(json.dumps(_cache_safe_ladder(ladder)))
    assert cached[0]["min_qty"] == 10
    assert Decimal(cached[0]["discount_percent"]) == Decimal("2.50")


# =========================================================
# ORM: денежные колонки приходят как Decimal
# =========================================================
async def test_orm_returns_decimal_for_money_columns(session_factory):
    """Аннотация модели обязана совпадать с фактическим типом Numeric.

    Пока ``Mapped[float]``, потребитель писал ``Decimal + float`` и падал в
    TypeError только на данных из БД.
    """
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    product = await create_product(sf, sku="D-1", name="Widget", brand=brand, base_price="10.10")
    rate = await set_rate(sf, currency="USD", rate="3.1234", scale=1)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand, percent=Decimal("12.5"))

    async with sf() as s:
        reloaded = await s.get(Product, product.id)
        assert isinstance(reloaded.base_price, Decimal)
        reloaded_rate = await s.get(ExchangeRate, rate.id)
        assert isinstance(reloaded_rate.rate, Decimal)
        reloaded_ub = await s.get(UserBrand, (user.id, brand.id))
        assert isinstance(reloaded_ub.discount_percent, Decimal)

    # Смешение денег и курса прямо на объектах модели не падает.
    assert Decimal(str(reloaded.base_price)) * reloaded_rate.scale >= Decimal(0)


# =========================================================
# Корзина v1: точность сложения и полу-копейка
# =========================================================
async def test_cart_sums_prices_without_float_tail(api_client, session_factory):
    """0.10 + 0.20 + 0.05 = 0.35 — не 0.35000000000000003."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    for sku, price in (("P-1", "0.10"), ("P-2", "0.20"), ("P-3", "0.05")):
        await create_product(sf, sku=sku, name=f"Item {sku}", brand=brand, base_price=price)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client)

    for sku in ("P-1", "P-2", "P-3"):
        r = await api_client.post("/api/v1/cart/items", json={"sku": sku, "quantity": 1})
        assert r.status_code == 201, r.text

    r = await api_client.get("/api/v1/cart")
    assert r.status_code == 200, r.text
    cart = r.json()
    by_sku = {item["sku"]: item for item in cart["items"]}
    assert by_sku["P-1"]["line_total"] == 0.10
    assert by_sku["P-2"]["line_total"] == 0.20
    # Контракт v1 не сломан: сумма — JSON-число, а не строка.
    assert cart["total_amount"] == 0.35
    assert isinstance(cart["total_amount"], (int, float))


async def test_cart_line_total_rounds_half_up(api_client, session_factory):
    """0.005 → 0.01 по HALF_UP: цена в копейках, а итог строки — с половиной."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="H-1", name="Half", brand=brand, base_price="4.01")
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand, percent=Decimal("50"))
    await _login(api_client)

    r = await api_client.post("/api/v1/cart/items", json={"sku": "H-1", "quantity": 3})
    assert r.status_code == 201, r.text
    cart = r.json()
    item = cart["items"][0]
    # 4.01 * 0.5 = 2.005 → 2.01; 2.01 * 3 = 6.03 (float+round дал бы 6.02)
    assert item["unit_price"] == 2.01
    assert item["line_total"] == 6.03
    assert cart["total_amount"] == 6.03


# =========================================================
# Заявка: Decimal-курс + Decimal-сумма, JSON-контракт прежний
# =========================================================
async def test_order_total_is_exact_decimal_sum(api_client, session_factory):
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="D-1", name="Widget", brand=brand, base_price="19.99")
    await create_product(sf, sku="D-2", name="Gadget", brand=brand, base_price="0.01")
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client)

    r = await api_client.post(
        "/api/v1/orders",
        json={
            "items": [
                {"sku": "D-1", "quantity": 7},
                {"sku": "D-2", "quantity": 3},
            ],
            "delivery_point": "Склад Минск",
        },
    )
    assert r.status_code == 201, r.text
    order = r.json()
    # 19.99 * 7 = 139.93, 0.01 * 3 = 0.03 → ровно 139.96
    assert order["total_amount"] == 139.96
    # Контракт v1 — числа; сложение их как float даёт 139.95999999999998,
    # поэтому клиент должен сводить сумму через str → Decimal (или на бэке).
    пересчёт = sum(
        Decimal(str(item["unit_price"])) * item["quantity"]
        for item in order["items"]
    )
    assert пересчёт == Decimal("139.96")

    async with sf() as s:
        stored = await s.get(Order, order["id"])
        assert isinstance(stored.total_amount, Decimal)
        assert stored.total_amount == Decimal("139.96")
        items = (
            await s.execute(
                select(OrderItem).where(OrderItem.order_id == stored.id)
            )
        ).scalars().all()
        assert [type(i.unit_price) for i in items] == [Decimal, Decimal]
        assert sorted(i.unit_price for i in items) == [
            Decimal("0.01"),
            Decimal("19.99"),
        ]


async def test_order_in_currency_uses_decimal_rate(api_client, session_factory):
    """Заявка в валюте: Decimal-цена × Decimal-курс без TypeError."""
    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="D-1", name="Widget", brand=brand, base_price="100.00")
    rate = await set_rate(sf, currency="USD", rate="3.1234", scale=1)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_fixed_rate_for_user(sf, user=user, rate=rate)
    await _login(api_client)

    r = await api_client.post(
        "/api/v1/orders",
        json={
            "items": [{"sku": "D-1", "quantity": 3}],
            "price_calc_mode": "fixed",
            "delivery_point": "Склад Минск",
        },
    )
    assert r.status_code == 201, r.text
    order = r.json()
    # 100 BYN / 3.1234 = 32.0164… → 32.02 за штуку; курс — с точностью колонки.
    assert order["currency_code"] == "USD"
    assert order["exchange_rate"] == 3.1234
    assert order["items"][0]["unit_price"] == 32.02
    assert order["total_amount"] == 96.06

    async with sf() as s:
        stored = await s.get(Order, order["id"])
        assert isinstance(stored.exchange_rate, Decimal)
        assert stored.exchange_rate == Decimal("3.1234")
        # Курс и сумма живут в одной модели и складываются без TypeError.
        assert stored.total_amount + stored.exchange_rate == Decimal("99.1834")


async def test_invoice_total_copied_as_decimal(api_client, session_factory):
    """Счёт — замороженная копия суммы заказа, тоже Decimal."""
    from app.services.invoice import InvoiceService

    sf = session_factory
    brand = await create_brand(sf, name="Alpha")
    await create_product(sf, sku="D-1", name="Widget", brand=brand, base_price="19.99")
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    manager = await create_user(
        sf, email="mgr@example.by", role=UserRole.MANAGER, password=PASSWORD
    )
    await _login(api_client)

    r = await api_client.post(
        "/api/v1/orders",
        json={
            "items": [{"sku": "D-1", "quantity": 7}],
            "delivery_point": "Склад Минск",
        },
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]

    invoice = await InvoiceService(sf()).issue(manager, order_id)
    assert isinstance(invoice.total_amount, Decimal)
    assert invoice.total_amount == Decimal("139.93")