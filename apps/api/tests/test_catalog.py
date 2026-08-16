"""Интеграционные тесты каталога/прайса. См. ARCHITECTURE_PLAN.md §6, §8, §17.

Покрытие:
  - список товаров: пагинация, поиск, фильтры по бренду/серии/складу
  - ценообразование: скидка % по бренду, override_price приоритет, без скидки
  - мультивалютность: BYN (по умолчанию), USD (конвертация), фиксация курса
  - price_calc_mode: fixed vs nbrb_current
  - /filters, /products/{sku}, /products/{sku}/price-history
  - RBAC: каталог требует авторизации
  - архив/soft-delete: удалённые товары не видны
"""

import uuid

from app.models.enums import StockStatus, UserRole
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
    set_discount,
    set_display_currency,
    set_fixed_rate_for_user,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


# ---------- helpers ----------
async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _seed_basic_catalog(sf):
    brand_a = await create_brand(sf, name="Alpha", slug="alpha")
    brand_b = await create_brand(sf, name="Beta", slug="beta")
    s1 = await create_series(sf, brand=brand_a, name="Serie X", photo_key="x.webp")
    p1 = await create_product(sf, sku="A-100", name="Widget One", brand=brand_a,
                              series=s1, base_price=100)
    p2 = await create_product(sf, sku="A-101", name="Widget Two", brand=brand_a,
                              series=s1, base_price=240)
    p3 = await create_product(sf, sku="B-200", name="Gadget", brand=brand_b,
                              base_price=89, stock=StockStatus.PREORDER)
    return brand_a, brand_b, s1, [p1, p2, p3]


# =========================================================
# AUTH / RBAC
# =========================================================
async def test_catalog_requires_auth(api_client):
    r = await api_client.get("/api/v1/catalog/products")
    assert r.status_code == 401


# =========================================================
# СПИСОК: пагинация, поиск, фильтры
# =========================================================
async def test_list_basic_and_pagination(api_client, session_factory):
    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/products?per_page=2&page=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 3
    assert body["meta"]["page"] == 1
    assert body["meta"]["per_page"] == 2

    r2 = await api_client.get("/api/v1/catalog/products?per_page=2&page=2")
    assert len(r2.json()["data"]) == 1


async def test_list_search_by_sku(api_client, session_factory):
    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/products?q=A-10")
    skus = [p["sku"] for p in r.json()["data"]]
    assert skus == ["A-100", "A-101"]


async def test_list_search_by_name_substring_case_insensitive(api_client, session_factory):
    """Поиск — подстрока без учёта регистра и по name (семантика ILIKE,
    которую ускоряют pg_trgm GIN-индексы; см. §5.2)."""
    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/products?q=wIdGeT")
    skus = [p["sku"] for p in r.json()["data"]]
    assert skus == ["A-100", "A-101"]

    r2 = await api_client.get("/api/v1/catalog/products?q=Gadget")
    assert [p["sku"] for p in r2.json()["data"]] == ["B-200"]


async def test_list_filter_by_brand(api_client, session_factory):
    sf = session_factory
    brand_a, brand_b, s1, _ = await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?brand={brand_b.id}")
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["brand"]["name"] == "Beta"


async def test_list_filter_by_stock(api_client, session_factory):
    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/products?stock=PREORDER")
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["stock_status"] == "PREORDER"


# =========================================================
# ЦЕНООБРАЗОВАНИЕ (§8)
# =========================================================
async def test_price_with_brand_discount(api_client, session_factory):
    sf = session_factory
    brand_a, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand_a, percent=10)  # 10% off
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p1.sku}")
    card = r.json()["data"][0]
    assert card["base_price_byn"] == 100.0
    assert card["client_price"] == 90.0      # 100 * 0.9
    assert card["has_discount"] is True


async def test_price_override_priority(api_client, session_factory):
    """override_price бьёт процент скидки (§8)."""
    sf = session_factory
    brand_a, _, _, _ = await _seed_basic_catalog(sf)
    p = await create_product(sf, sku="OVR-1", name="Override Item", brand=brand_a,
                             base_price=200, override_price=150)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_discount(sf, user=user, brand=brand_a, percent=30)  # было бы 140
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p.sku}")
    card = r.json()["data"][0]
    assert card["client_price"] == 150.0  # override, а не 140
    assert card["currency"] == "BYN"


async def test_price_no_discount_for_client(api_client, session_factory):
    sf = session_factory
    _, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p1.sku}")
    card = r.json()["data"][0]
    assert card["client_price"] == card["retail_price"]
    assert card["has_discount"] is False


async def test_manager_sees_retail_no_discount(api_client, session_factory):
    """У менеджера нет скидок → client_price == retail."""
    sf = session_factory
    brand_a, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p1.sku}")
    card = r.json()["data"][0]
    assert card["client_price"] == card["retail_price"] == 100.0


# =========================================================
# МУЛЬТИВАЛЮТНОСТЬ (§17)
# =========================================================
async def test_currency_conversion_usd(api_client, session_factory):
    sf = session_factory
    brand_a, _, _, [p1, *_] = await _seed_basic_catalog(sf)  # base_price 100 BYN
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_rate(sf, currency="USD", rate=3.27, scale=1)
    await set_display_currency(sf, user=user, currency="USD")
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p1.sku}")
    card = r.json()["data"][0]
    assert card["currency"] == "USD"
    assert card["rate_source"] == "NBRB"
    # 100 BYN / 3.27 ≈ 30.58
    assert abs(card["retail_price"] - 30.58) < 0.01


async def test_fixed_rate_overrides_nbrb(api_client, session_factory):
    """Если у клиента зафиксирован курс — используется он (calc_mode=fixed)."""
    sf = session_factory
    brand_a, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_rate(sf, currency="USD", rate=3.27, scale=1)  # текущий НБ РБ
    fixed = await set_rate(sf, currency="USD", rate=3.0, scale=1, source="MANUAL")
    await set_fixed_rate_for_user(sf, user=user, rate=fixed)
    await _login(api_client, CLIENT_EMAIL)

    # fixed (по умолчанию) → курс 3.0 → 100/3 = 33.33
    r = await api_client.get(
        f"/api/v1/catalog/products?q={p1.sku}&price_calc_mode=fixed"
    )
    card = r.json()["data"][0]
    assert card["rate_source"] == "FIXED"
    assert abs(card["retail_price"] - 33.33) < 0.01

    # nbrb_current → курс 3.27 → 30.58
    r2 = await api_client.get(
        f"/api/v1/catalog/products?q={p1.sku}&price_calc_mode=nbrb_current"
    )
    card2 = r2.json()["data"][0]
    assert card2["rate_source"] == "NBRB"
    assert abs(card2["retail_price"] - 30.58) < 0.01


async def test_no_rate_falls_back_to_byn(api_client, session_factory):
    """Если для display-валюты нет курса — показываем в BYN."""
    sf = session_factory
    brand_a, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await set_display_currency(sf, user=user, currency="EUR")  # курса EUR нет
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products?q={p1.sku}")
    card = r.json()["data"][0]
    assert card["currency"] == "BYN"   # fallback
    assert card["retail_price"] == 100.0


# =========================================================
# ФИЛЬТРЫ / ДЕТАЛИ / ИСТОРИЯ
# =========================================================
async def test_filters_endpoint(api_client, session_factory):
    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/filters")
    body = r.json()
    assert {b["name"] for b in body["brands"]} == {"Alpha", "Beta"}
    assert "IN_STOCK" in body["stock"]


async def test_product_detail(api_client, session_factory):
    sf = session_factory
    _, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get(f"/api/v1/catalog/products/{p1.sku}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sku"] == p1.sku
    assert body["brand"]["name"] == "Alpha"
    assert body["series"]["name"] == "Serie X"


async def test_attributes_surfaced_in_list_and_detail(api_client, session_factory):
    """Характеристики товара (JSONB) отдаются в списке и в карточке (§5)."""
    sf = session_factory
    brand_a, _, s1, _ = await _seed_basic_catalog(sf)
    attrs = {"modules": 12, "color": "Черный", "ip_rating": "IP40"}
    p = await create_product(
        sf, sku="OPT-12", name="OptiBox Pro 12-NKR", brand=brand_a,
        series=s1, base_price=29.60, attributes=attrs,
    )
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    # список
    r = await api_client.get(f"/api/v1/catalog/products?q={p.sku}")
    card = r.json()["data"][0]
    assert card["attributes"]["modules"] == 12
    assert card["attributes"]["color"] == "Черный"
    assert card["attributes"]["ip_rating"] == "IP40"

    # карточка
    r2 = await api_client.get(f"/api/v1/catalog/products/{p.sku}")
    body = r2.json()
    assert body["attributes"] == attrs
    assert body["base_price_byn"] == 29.60


async def test_product_not_found(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.get("/api/v1/catalog/products/NOPE-999")
    assert r.status_code == 404


async def test_price_history_empty(api_client, session_factory):
    sf = session_factory
    _, _, _, [p1, *_] = await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.get(f"/api/v1/catalog/products/{p1.sku}/price-history")
    assert r.status_code == 200
    assert r.json() == []  # история пишется при импорте (Этап 4)


# =========================================================
# SOFT DELETE / АРХИВ
# =========================================================
async def test_archived_products_hidden(api_client, session_factory):
    sf = session_factory
    await create_product(sf, sku="ARCH-1", name="Old", stock=StockStatus.ARCHIVED)
    await create_product(sf, sku="LIVE-1", name="Live")
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.get("/api/v1/catalog/products")
    skus = [p["sku"] for p in r.json()["data"]]
    assert "LIVE-1" in skus
    assert "ARCH-1" not in skus


# =========================================================
# FAIL-OPEN: каталог жив при лежащем Redis (§4)
# =========================================================
class _BrokenRedis:
    async def get(self, key):
        raise ConnectionError("redis down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    async def sadd(self, key, value):
        raise ConnectionError("redis down")

    async def delete(self, *keys):
        raise ConnectionError("redis down")


async def test_catalog_served_from_db_when_redis_down(
    api_client, session_factory, monkeypatch
):
    from app.services import cache as cache_module

    sf = session_factory
    await _seed_basic_catalog(sf)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    monkeypatch.setattr(cache_module.cache, "redis", _BrokenRedis())

    r = await api_client.get("/api/v1/catalog/products?q=widget")
    assert r.status_code == 200, r.text
    skus = [p["sku"] for p in r.json()["data"]]
    assert skus == ["A-100", "A-101"]  # данные из БД, не из кэша

    # повторный запрос (путь записи в кэш) тоже не валится
    r2 = await api_client.get("/api/v1/catalog/products?q=widget")
    assert r2.status_code == 200
    assert [p["sku"] for p in r2.json()["data"]] == ["A-100", "A-101"]


# =========================================================
# РЕПОЗИТОРИЙ: get_brand / get_series (карточка товара)
# =========================================================
async def test_repo_get_brand_and_series(session_factory):
    from app.repositories import catalog as catalog_repo

    sf = session_factory
    brand_a, _brand_b, s1, _products = await _seed_basic_catalog(sf)

    async with sf() as s:
        b = await catalog_repo.get_brand(s, brand_a.id)
        assert b is not None and b.name == "Alpha"
        assert await catalog_repo.get_brand(s, uuid.uuid4()) is None

        ser = await catalog_repo.get_series(s, s1.id)
        assert ser is not None and ser.name == "Serie X"
        assert await catalog_repo.get_series(s, uuid.uuid4()) is None
