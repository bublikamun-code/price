"""Контрактные тесты API v2 «Скидки за объём» (§6, §16 п.41).

Покрывают канон:
  * CRUD лестницы бренда: GET/POST/PATCH/DELETE, выдача по возрастанию порога;
  * ``If-Match`` сверяет версию **ступени**: без заголовка → 400, устаревшая →
    409 ``STALE_RESOURCE_VERSION``, свежая → 200 и ``version + 1``;
  * домены значений ``min_qty >= 1`` и ``0 < discountPercent < 100`` → 422;
  * дубль порога в пределах бренда → 409 ``VOLUME_TIER_DUPLICATE_THRESHOLD``;
  * RBAC: клиент → 403, аноним → 401;
  * каталог публикует лестницу (``volumeTiers``) и НЕ применяет её к
    ``clientPrice``; корзина и заказ выбирают ступень по количеству строки;
  * «максимум из двух»: скидка бренда и ступень объёма не складываются, а
    ``override_price`` неуязвим к обеим;
  * правка ступени инвалидирует кэш ``volume-tiers`` — следующая корзина
    видит новый процент;
  * аудит create/update/delete.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import BrandVolumeTier
from app.models.enums import UserRole
from app.models.order import Order, OrderItem
from app.models.system import AuditLog
from app.services.cache import VOLUME_TIERS_TAG, cache
from tests.conftest import (
    create_brand,
    create_product,
    create_user,
    set_discount,
)

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "v2-tier-manager@example.by"
CLIENT_EMAIL = "v2-tier-client@example.by"


# ------------------------------------------------------------------ helpers
async def _login(api_client, email: str) -> None:
    response = await api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


async def _logout(api_client) -> None:
    await api_client.post("/api/v1/auth/logout")


async def _manager(session_factory, email: str = MANAGER_EMAIL):
    return await create_user(
        session_factory, email=email, role=UserRole.MANAGER, password=PASSWORD
    )


async def _client(session_factory, email: str = CLIENT_EMAIL):
    return await create_user(
        session_factory, email=email, role=UserRole.CLIENT, password=PASSWORD
    )


async def _create_tier(
    api_client, brand_id, *, min_qty: int, discount_percent: float
) -> dict:
    response = await api_client.post(
        f"/api/v2/manager/brands/{brand_id}/volume-tiers",
        json={"minQty": min_qty, "discountPercent": discount_percent},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _seed_tier(session_factory, *, brand_id, min_qty: int, percent: str):
    async with session_factory() as session:
        tier = BrandVolumeTier(
            brand_id=brand_id, min_qty=min_qty, discount_percent=Decimal(percent)
        )
        session.add(tier)
        await session.commit()
        await session.refresh(tier)
        return tier


def _order_payload(product, quantity: str) -> dict:
    return {
        "draftId": None,
        "items": [
            {
                "productId": str(product.id),
                "quantity": quantity,
                "note": None,
            }
        ],
        "delivery": {
            "method": "DELIVERY",
            "contactName": "Иван",
            "phone": "+375291234567",
            "preferredDate": "2026-10-02",
            "comment": "После 14:00",
        },
    }


# ------------------------------------------------------------------- CRUD
async def test_create_and_list_tiers_sorted_by_threshold(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)

    # Создаём вразнобой — выдача обязана быть по возрастанию порога.
    third = await _create_tier(api_client, brand.id, min_qty=100, discount_percent=9)
    first = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)
    second = await _create_tier(api_client, brand.id, min_qty=50, discount_percent=5)

    for tier in (first, second, third):
        assert tier["brandId"] == str(brand.id)
        assert tier["version"] == 1
        assert set(tier) == {
            "id",
            "brandId",
            "minQty",
            "discountPercent",
            "version",
            "createdAt",
            "updatedAt",
        }
    assert float(first["discountPercent"]) == 2.0

    response = await api_client.get(f"/api/v2/manager/brands/{brand.id}/volume-tiers")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [t["minQty"] for t in data] == [10, 50, 100]
    assert [t["id"] for t in data] == [first["id"], second["id"], third["id"]]


async def test_list_tiers_of_unknown_brand_is_404(api_client, session_factory):
    await _manager(session_factory)
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.get(
        f"/api/v2/manager/brands/{uuid.uuid4()}/volume-tiers"
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "VOLUME_TIER_NOT_FOUND"
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_update_tier_bumps_version_and_keeps_threshold(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    response = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        headers={"If-Match": "1"},
        json={"discountPercent": 4.5},
    )
    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["version"] == 2
    # Порог не передан — остаётся прежним (PATCH, не PUT).
    assert updated["minQty"] == 10
    assert float(updated["discountPercent"]) == 4.5


async def test_delete_tier_removes_it(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    response = await api_client.delete(
        f"/api/v2/manager/volume-tiers/{tier['id']}", headers={"If-Match": "1"}
    )
    assert response.status_code == 204, response.text
    assert response.content == b""

    listing = await api_client.get(f"/api/v2/manager/brands/{brand.id}/volume-tiers")
    assert listing.json()["data"] == []

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(BrandVolumeTier).where(BrandVolumeTier.id == tier["id"])
            )
            is None
        )


# --------------------------------------------------------------- If-Match
async def test_patch_without_if_match_is_400(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    response = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        json={"discountPercent": 4},
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_IF_MATCH"


async def test_delete_without_if_match_is_400(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    response = await api_client.delete(f"/api/v2/manager/volume-tiers/{tier['id']}")
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_IF_MATCH"


async def test_stale_if_match_is_409(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    first = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        headers={"If-Match": "1"},
        json={"discountPercent": 4},
    )
    assert first.status_code == 200, first.text

    stale = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        headers={"If-Match": "1"},
        json={"discountPercent": 6},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "STALE_RESOURCE_VERSION"

    stale_delete = await api_client.delete(
        f"/api/v2/manager/volume-tiers/{tier['id']}", headers={"If-Match": "1"}
    )
    assert stale_delete.status_code == 409, stale_delete.text
    assert stale_delete.json()["code"] == "STALE_RESOURCE_VERSION"


@pytest.mark.parametrize("if_match", ['"1"', 'W/"1"', "1"])
async def test_if_match_accepts_quoted_forms(api_client, session_factory, if_match):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    response = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        headers={"If-Match": if_match},
        json={"discountPercent": 3},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["version"] == 2


# ------------------------------------------------------------- валидация
@pytest.mark.parametrize(
    "payload",
    [
        {"minQty": 0, "discountPercent": 5},
        {"minQty": -3, "discountPercent": 5},
        {"minQty": 10, "discountPercent": 0},
        {"minQty": 10, "discountPercent": 100},
        {"minQty": 10, "discountPercent": -2},
    ],
)
async def test_invalid_ranges_are_422(api_client, session_factory, payload):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)

    response = await api_client.post(
        f"/api/v2/manager/brands/{brand.id}/volume-tiers", json=payload
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_duplicate_threshold_is_409(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)

    duplicate = await api_client.post(
        f"/api/v2/manager/brands/{brand.id}/volume-tiers",
        json={"minQty": 10, "discountPercent": 7},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "VOLUME_TIER_DUPLICATE_THRESHOLD"


async def test_patch_into_duplicate_threshold_is_409(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)
    other = await _create_tier(api_client, brand.id, min_qty=50, discount_percent=5)

    response = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{other['id']}",
        headers={"If-Match": "1"},
        json={"minQty": 10},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "VOLUME_TIER_DUPLICATE_THRESHOLD"


async def test_same_threshold_in_other_brand_is_allowed(api_client, session_factory):
    await _manager(session_factory)
    first_brand = await create_brand(session_factory, name="Brand One")
    second_brand = await create_brand(session_factory, name="Brand Two")
    await _login(api_client, MANAGER_EMAIL)
    await _create_tier(api_client, first_brand.id, min_qty=10, discount_percent=2)

    response = await api_client.post(
        f"/api/v2/manager/brands/{second_brand.id}/volume-tiers",
        json={"minQty": 10, "discountPercent": 3},
    )
    assert response.status_code == 201, response.text


# ------------------------------------------------------------------- RBAC
async def test_client_cannot_manage_tiers(api_client, session_factory):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, CLIENT_EMAIL)

    listing = await api_client.get(f"/api/v2/manager/brands/{brand.id}/volume-tiers")
    assert listing.status_code == 403, listing.text

    created = await api_client.post(
        f"/api/v2/manager/brands/{brand.id}/volume-tiers",
        json={"minQty": 10, "discountPercent": 2},
    )
    assert created.status_code == 403, created.text


async def test_anonymous_cannot_read_tiers(api_client, session_factory):
    brand = await create_brand(session_factory, name="Tier Brand")

    response = await api_client.get(f"/api/v2/manager/brands/{brand.id}/volume-tiers")
    assert response.status_code == 401, response.text


# ------------------------------------------------------------------ аудит
async def test_mutations_are_audited(api_client, session_factory):
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await _login(api_client, MANAGER_EMAIL)
    tier = await _create_tier(api_client, brand.id, min_qty=10, discount_percent=2)
    await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier['id']}",
        headers={"If-Match": "1"},
        json={"discountPercent": 4},
    )
    await api_client.delete(
        f"/api/v2/manager/volume-tiers/{tier['id']}", headers={"If-Match": "2"}
    )

    async with session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.target_type == "brand_volume_tier")
                .order_by(AuditLog.created_at)
            )
        ).all()
    assert actions == ["volume_tier.create", "volume_tier.update", "volume_tier.delete"]


# ------------------------------------------- каталог публикует лестницу
async def test_catalog_exposes_ladder_without_applying_it(api_client, session_factory):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    await create_product(
        session_factory, sku="TIER-1", name="Volume product", brand=brand, base_price=100
    )
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=50, percent="5")
    await _login(api_client, CLIENT_EMAIL)

    response = await api_client.get("/api/v2/catalog/products", params={"q": "TIER-1"})
    assert response.status_code == 200, response.text
    products = response.json()["data"]
    assert len(products) == 1, products
    product = products[0]
    assert product["volumeTiers"] == [
        {"minQty": 10, "discountPercent": 2.0},
        {"minQty": 50, "discountPercent": 5.0},
    ]
    # Каталог не знает количества строки — цена остаётся розничной/брендовой.
    assert product["clientPrice"]["amount"] == "100.00"


# ------------------------------------------- корзина применяет ступень
async def _add_to_cart(api_client, product, quantity: int, *, if_match: str = "1") -> dict:
    response = await api_client.post(
        "/api/v2/cart/items",
        json={"productId": str(product.id), "quantity": str(quantity)},
        headers={"If-Match": if_match},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_cart_line_carries_reached_tier_and_discounted_price(
    api_client, session_factory
):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-CART", name="Cart product", brand=brand, base_price=100
    )
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=50, percent="5")
    await _login(api_client, CLIENT_EMAIL)

    cart = await _add_to_cart(api_client, product, 50)
    line = cart["items"][0]
    assert line["volumeTier"] == {"minQty": 50, "discountPercent": 5.0}
    assert line["unitPrice"] == {"amount": "95.00", "currency": "BYN"}
    assert line["lineTotal"] == {"amount": "4750.00", "currency": "BYN"}
    assert cart["total"] == {"amount": "4750.00", "currency": "BYN"}


async def test_cart_line_below_threshold_has_no_tier(api_client, session_factory):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-LOW", name="Low qty", brand=brand, base_price=100
    )
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")
    await _login(api_client, CLIENT_EMAIL)

    cart = await _add_to_cart(api_client, product, 9)
    line = cart["items"][0]
    assert line["volumeTier"] is None
    assert line["unitPrice"] == {"amount": "100.00", "currency": "BYN"}


# ------------------------------------------- «максимум из двух» (§8)
async def test_volume_tier_and_brand_discount_take_max_not_sum(
    api_client, session_factory
):
    user = await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-MAX", name="Max", brand=brand, base_price=100
    )
    # Скидка бренда 8% выше объёмных 2% и 5% → побеждает 8%, а не 13%.
    await set_discount(session_factory, user=user, brand=brand, percent=8)
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=50, percent="5")
    await _login(api_client, CLIENT_EMAIL)

    cart = await _add_to_cart(api_client, product, 50)
    line = cart["items"][0]
    assert line["volumeTier"] == {"minQty": 50, "discountPercent": 5.0}
    assert line["unitPrice"] == {"amount": "92.00", "currency": "BYN"}


async def test_volume_tier_wins_when_greater_than_brand_discount(
    api_client, session_factory
):
    user = await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-HIGH", name="High", brand=brand, base_price=100
    )
    await set_discount(session_factory, user=user, brand=brand, percent=3)
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=100, percent="9")
    await _login(api_client, CLIENT_EMAIL)

    cart = await _add_to_cart(api_client, product, 120)
    assert cart["items"][0]["unitPrice"] == {"amount": "91.00", "currency": "BYN"}


async def test_override_price_is_immune_to_volume_discount(api_client, session_factory):
    user = await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory,
        sku="TIER-OVERRIDE",
        name="Override",
        brand=brand,
        base_price=100,
        override_price=77,
    )
    await set_discount(session_factory, user=user, brand=brand, percent=15)
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="20")
    await _login(api_client, CLIENT_EMAIL)

    cart = await _add_to_cart(api_client, product, 100)
    line = cart["items"][0]
    # Ступень в ответе остаётся (менеджер её задал), но цену не двигает.
    assert line["volumeTier"] == {"minQty": 10, "discountPercent": 20.0}
    assert line["unitPrice"] == {"amount": "77.00", "currency": "BYN"}


# ------------------------------------------------- инвалидация кэша
async def test_tier_update_invalidates_cache(api_client, session_factory):
    await _client(session_factory)
    await _manager(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-CACHE", name="Cache", brand=brand, base_price=100
    )
    tier = await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")

    await _login(api_client, CLIENT_EMAIL)
    first = await _add_to_cart(api_client, product, 10)
    assert first["items"][0]["unitPrice"] == {"amount": "98.00", "currency": "BYN"}

    # Прогрев кэша состоялся: лестница лежит в Redis.
    warm = await cache.redis.keys(f"{cache.prefix}:cache:volume-tiers:*")
    assert warm, "лестница должна была закэшироваться"

    await _logout(api_client)
    await _login(api_client, MANAGER_EMAIL)
    patched = await api_client.patch(
        f"/api/v2/manager/volume-tiers/{tier.id}",
        headers={"If-Match": str(tier.version)},
        json={"discountPercent": 7},
    )
    assert patched.status_code == 200, patched.text

    # Инвалидация по тегу volume-tiers должна была снести прогретый кэш.
    still_cached = await cache.redis.keys(f"{cache.prefix}:cache:volume-tiers:*")
    assert not still_cached, "правка ступени обязана инвалидировать volume-tiers"

    await _logout(api_client)
    await _login(api_client, CLIENT_EMAIL)
    second = await _add_to_cart(api_client, product, 10, if_match="2")
    assert second["items"][0]["unitPrice"] == {"amount": "93.00", "currency": "BYN"}
    assert second["items"][0]["volumeTier"]["discountPercent"] == 7.0


def test_volume_tiers_tag_name():
    """Тег зафиксирован в каноне (§16 п.41 п.9) — переименование ломает
    инвалидацию, поэтому имя проверяется явно."""
    assert VOLUME_TIERS_TAG == "volume-tiers"


# ------------------------------------------- заказ фиксирует цену строки
async def test_order_keeps_frozen_unit_price_after_tier_change(
    api_client, session_factory
):
    """Цена строки заказа не пересчитывается (§8, §16 п.41 п.7)."""
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Tier Brand")
    product = await create_product(
        session_factory, sku="TIER-ORDER", name="Order", brand=brand, base_price=100
    )
    await _seed_tier(session_factory, brand_id=brand.id, min_qty=10, percent="2")
    await _login(api_client, CLIENT_EMAIL)

    created = await api_client.post(
        "/api/v2/orders",
        json=_order_payload(product, "10"),
        headers={"Idempotency-Key": "tier-order-1"},
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["data"]["id"]

    async with session_factory() as session:
        item = await session.scalar(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        assert item is not None
        assert Decimal(item.unit_price) == Decimal("98.00")

    # Меняем ступень так, что пересчёт дал бы вдвое меньшую цену.
    async with session_factory() as session:
        row = await session.get(BrandVolumeTier, (await _first_tier_id(session, brand.id)))
        row.discount_percent = Decimal("50")
        await session.commit()

    detail = await api_client.get(f"/api/v2/orders/{order_id}")
    assert detail.status_code == 200, detail.text

    async with session_factory() as session:
        item = await session.scalar(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        order = await session.get(Order, order_id)
        # Ни цена строки, ни итог заказа не изменились.
        assert Decimal(item.unit_price) == Decimal("98.00")
        assert Decimal(order.total_amount) == Decimal("980.00")


async def _first_tier_id(session, brand_id) -> uuid.UUID:
    return await session.scalar(
        select(BrandVolumeTier.id).where(BrandVolumeTier.brand_id == brand_id)
    )
