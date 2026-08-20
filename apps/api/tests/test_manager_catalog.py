"""Тесты товаров менеджер-панели (/manager/products). См. §6, §16 п.20-2.

Список с фильтрами (q/brand_id/stock) и пагинацией; PATCH ручной цены
(в т.ч. null = сброс) и статуса остатка + audit_log; RBAC.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.catalog import Product
from app.models.enums import StockStatus, UserRole
from app.models.system import AuditLog
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


async def _login(api_client, email, password=PASSWORD):
    return await api_client.post("/api/v1/auth/login",
                                 json={"email": email, "password": password})


async def _login_manager(api_client, sf):
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER,
                                password=PASSWORD)
    r = await _login(api_client, MANAGER_EMAIL)
    assert r.status_code == 200, r.text
    return manager


async def _seed_catalog(sf):
    """2 бренда, серия, 3 живых товара (разные статусы) + 1 удалённый."""
    alpha = await create_brand(sf, name="Alpha")
    beta = await create_brand(sf, name="Beta")
    serie = await create_series(sf, brand=alpha, name="Serie X")
    widget = await create_product(sf, sku="A-1", name="Widget", brand=alpha, series=serie,
                                  base_price=Decimal("100.00"))
    await create_product(sf, sku="A-2", name="Wadget", brand=alpha,
                         base_price=Decimal("50.00"), stock=StockStatus.PREORDER)
    doohickey = await create_product(sf, sku="B-1", name="Doohickey", brand=beta,
                                     base_price=Decimal("10.00"),
                                     stock=StockStatus.ARCHIVED)
    gone = await create_product(sf, sku="G-1", name="Gone", brand=alpha,
                                base_price=Decimal("1.00"))
    async with sf() as s:
        db_product = await s.get(Product, gone.id)
        db_product.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    return alpha, beta, serie, widget, doohickey, gone


# ------------------------------------------------------------------- RBAC
async def test_products_require_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.get("/api/v1/manager/products")).status_code == 403
    assert (
        await api_client.patch(
            f"/api/v1/manager/products/{uuid.uuid4()}",
            json={"stock_status": "PREORDER"},
        )
    ).status_code == 403


# ------------------------------------------------------------------- list
async def test_list_products_row_shape_and_sort(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    alpha, beta, serie, widget, doohickey, _ = await _seed_catalog(sf)

    r = await api_client.get("/api/v1/manager/products")
    assert r.status_code == 200, r.text
    body = r.json()
    # сортировка по имени; ARCHIVED виден менеджеру, удалённый — нет
    assert body["meta"] == {"page": 1, "per_page": 20, "total": 3}
    assert [row["name"] for row in body["data"]] == ["Doohickey", "Wadget", "Widget"]

    row = next(item for item in body["data"] if item["sku"] == "A-1")
    assert row["id"] == str(widget.id)
    assert row["brand"] == {"id": str(alpha.id), "name": "Alpha"}
    assert row["series"] == {"id": str(serie.id), "name": "Serie X"}
    assert Decimal(row["base_price"]) == Decimal("100.00")
    assert row["override_price"] is None
    assert row["stock_status"] == "IN_STOCK"

    # товар без серии: series = null
    row_a2 = next(item for item in body["data"] if item["sku"] == "A-2")
    assert row_a2["series"] is None


async def test_list_products_filters_and_pagination(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    alpha, beta, _, _, _, _ = await _seed_catalog(sf)

    # q — подстрока в имени (регистронезависимо), как в клиентском каталоге
    r = await api_client.get("/api/v1/manager/products", params={"q": "wadge"})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["sku"] == "A-2"

    # q — подстрока в артикуле
    r = await api_client.get("/api/v1/manager/products", params={"q": "B-1"})
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["sku"] == "B-1"

    # brand_id
    r = await api_client.get("/api/v1/manager/products", params={"brand_id": str(alpha.id)})
    assert r.json()["meta"]["total"] == 2
    assert all(row["brand"]["id"] == str(alpha.id) for row in r.json()["data"])

    # stock
    r = await api_client.get("/api/v1/manager/products",
                             params={"stock": StockStatus.PREORDER.value})
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["sku"] == "A-2"

    r = await api_client.get("/api/v1/manager/products",
                             params={"stock": StockStatus.ARCHIVED.value})
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["sku"] == "B-1"

    # пагинация
    r = await api_client.get("/api/v1/manager/products",
                             params={"page": 1, "per_page": 2})
    assert len(r.json()["data"]) == 2
    assert r.json()["meta"]["total"] == 3
    r = await api_client.get("/api/v1/manager/products",
                             params={"page": 2, "per_page": 2})
    assert len(r.json()["data"]) == 1


# ------------------------------------------------------------------ patch
async def test_patch_override_price_and_audit(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)
    _, _, _, widget, _, _ = await _seed_catalog(sf)

    r = await api_client.patch(
        f"/api/v1/manager/products/{widget.id}", json={"override_price": "99.90"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["override_price"]) == Decimal("99.90")
    assert body["sku"] == "A-1"

    async with sf() as s:
        db_product = await s.get(Product, widget.id)
        assert Decimal(str(db_product.override_price)) == Decimal("99.90")
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "product.update")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].actor_id == manager.id
    assert entries[0].target_type == "product"
    assert entries[0].target_id == widget.id
    assert entries[0].before == {"override_price": None}
    assert entries[0].after == {"override_price": "99.90"}


async def test_patch_override_price_null_resets(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    _, _, _, widget, _, _ = await _seed_catalog(sf)
    async with sf() as s:
        db_product = await s.get(Product, widget.id)
        db_product.override_price = Decimal("77.00")
        await s.commit()

    r = await api_client.patch(
        f"/api/v1/manager/products/{widget.id}", json={"override_price": None}
    )
    assert r.status_code == 200, r.text
    assert r.json()["override_price"] is None
    async with sf() as s:
        assert (await s.get(Product, widget.id)).override_price is None


async def test_patch_stock_status_and_combined_audit(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)
    _, _, _, widget, _, _ = await _seed_catalog(sf)

    r = await api_client.patch(
        f"/api/v1/manager/products/{widget.id}",
        json={"override_price": "10.00", "stock_status": "PREORDER"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["override_price"]) == Decimal("10.00")
    assert body["stock_status"] == "PREORDER"

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "product.update")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].actor_id == manager.id
    assert entries[0].before == {"override_price": None, "stock_status": "IN_STOCK"}
    assert entries[0].after == {"override_price": "10.00", "stock_status": "PREORDER"}


async def test_patch_product_errors(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    _, _, _, widget, _, gone = await _seed_catalog(sf)

    # неизвестный товар → 404
    r = await api_client.patch(
        f"/api/v1/manager/products/{uuid.uuid4()}", json={"stock_status": "PREORDER"}
    )
    assert r.status_code == 404, r.text

    # удалённый товар → 404
    r = await api_client.patch(
        f"/api/v1/manager/products/{gone.id}", json={"stock_status": "PREORDER"}
    )
    assert r.status_code == 404, r.text

    # пустой PATCH → 422 (нужно хотя бы одно поле)
    r = await api_client.patch(f"/api/v1/manager/products/{widget.id}", json={})
    assert r.status_code == 422, r.text

    # отрицательная цена → 422 (Pydantic ge=0)
    r = await api_client.patch(
        f"/api/v1/manager/products/{widget.id}", json={"override_price": "-1"}
    )
    assert r.status_code == 422, r.text

    # несуществующий статус → 422
    r = await api_client.patch(
        f"/api/v1/manager/products/{widget.id}", json={"stock_status": "NOPE"}
    )
    assert r.status_code == 422, r.text
