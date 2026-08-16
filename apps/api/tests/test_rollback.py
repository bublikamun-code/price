"""Тесты отката версии прайс-листа (§16 п.14).

Сценарии:
  1. happy path: restore цен из последнего «чужого» снапшота (changed_at DESC),
     архивация впервые появившихся товаров, аудит rolled_back_at/by,
     архивный товар пропадает из каталога.
  2. Гварды 409: не последняя DONE-версия; повторный откат; не-DONE статус.
  3. 404 — неизвестная версия; 403 — клиентская роль.
  4. Кэш: после commit инвалидируются теги catalog/filters.
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.catalog import PriceHistory, PriceListVersion, Product
from app.models.enums import (
    ImportMode,
    PriceListVersionStatus,
    StockStatus,
    UserRole,
)
from app.services import price_list_import as pli_service
from app.services.cache import CATALOG_TAG, FILTERS_TAG
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"

_BASE = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


# ---------- seed helpers ----------
async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _make_version(
    sf,
    *,
    manager,
    filename="p.csv",
    status=PriceListVersionStatus.DONE,
    created_at=None,
) -> PriceListVersion:
    async with sf() as s:
        v = PriceListVersion(
            uploaded_by=manager.id,
            filename=filename,
            import_mode=ImportMode.UPSERT,
            status=status,
            base_currency="BYN",
            rate_to_byn=1,
            rate_source="MANUAL",
            created_at=created_at or _BASE,
        )
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


async def _make_product(sf, *, sku, name, base_price, version_id=None) -> Product:
    async with sf() as s:
        p = Product(
            sku=sku,
            name=name,
            base_price=base_price,
            stock_status=StockStatus.IN_STOCK,
            attributes={},
            price_list_version_id=version_id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def _reprice(sf, product, *, version_id, base_price, override_price=None):
    """«Импорт» версии: переоценка товара и смена принадлежности."""
    async with sf() as s:
        db_p = await s.get(Product, product.id)
        db_p.price_list_version_id = version_id
        db_p.base_price = base_price
        db_p.override_price = override_price
        await s.commit()


async def _add_history(
    sf, *, product, version_id, base_price, override_price=None, changed_at
) -> None:
    async with sf() as s:
        s.add(
            PriceHistory(
                product_id=product.id,
                base_price=base_price,
                override_price=override_price,
                price_list_version_id=version_id,
                changed_at=changed_at,
            )
        )
        await s.commit()


async def _seed_two_versions(sf, *, manager):
    """v0/v1/v2 — DONE по возрастанию created_at.

    A и B переоценены в v2 (есть «чужие» снапшоты → restore). У B два снапшота
    до v2 (v0 и v1) — восстановиться должен именно из v1 (changed_at DESC).
    C впервые появился в v2 (снапшоты только v2) → архивация.
    """
    v0 = await _make_version(sf, manager=manager, filename="v0.csv", created_at=_BASE)
    v1 = await _make_version(
        sf, manager=manager, filename="v1.csv", created_at=_BASE + timedelta(minutes=10)
    )
    v2 = await _make_version(
        sf, manager=manager, filename="v2.csv", created_at=_BASE + timedelta(minutes=20)
    )
    t0 = _BASE + timedelta(seconds=1)
    t1 = _BASE + timedelta(minutes=11)
    t2 = _BASE + timedelta(minutes=21)

    a = await _make_product(sf, sku="A-1", name="Widget", base_price=Decimal("100.00"))
    b = await _make_product(sf, sku="B-2", name="Gadget", base_price=Decimal("200.00"))

    # история до v2: у A один снапшот v1; у B два — последний от v1, не от v0
    await _add_history(sf, product=a, version_id=v1.id,
                        base_price=Decimal("100.00"), override_price=Decimal("90.00"),
                        changed_at=t1)
    await _add_history(sf, product=b, version_id=v0.id,
                        base_price=Decimal("150.00"), changed_at=t0)
    await _add_history(sf, product=b, version_id=v1.id,
                        base_price=Decimal("200.00"), changed_at=t1)

    # v2 переоценила A и B
    await _reprice(sf, a, version_id=v2.id, base_price=Decimal("150.00"),
                   override_price=Decimal("140.00"))
    await _reprice(sf, b, version_id=v2.id, base_price=Decimal("260.00"))
    await _add_history(sf, product=a, version_id=v2.id,
                       base_price=Decimal("150.00"), override_price=Decimal("140.00"),
                       changed_at=t2)
    await _add_history(sf, product=b, version_id=v2.id,
                       base_price=Decimal("260.00"), changed_at=t2)

    # C — новый товар v2
    c = await _make_product(sf, sku="C-3", name="Fresh", base_price=Decimal("300.00"),
                            version_id=v2.id)
    await _add_history(sf, product=c, version_id=v2.id,
                       base_price=Decimal("300.00"), changed_at=t2)

    return v0, v1, v2, a, b, c


# ===========================================================================
# 1. Happy path
# ===========================================================================
@pytest.mark.asyncio
class TestRollbackHappyPath:
    async def test_restore_and_archive(self, api_client, session_factory):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        v0, v1, v2, a, b, c = await _seed_two_versions(sf, manager=mgr)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["restored"] == 2
        assert body["archived"] == 1
        assert body["version"]["id"] == str(v2.id)
        assert body["version"]["rolled_back_at"] is not None
        assert body["version"]["rolled_back_by"] == str(mgr.id)

        async with sf() as s:
            # A: цены из снапшота v1 (включая override), версия — v1
            db_a = await s.get(Product, a.id)
            assert db_a.base_price == Decimal("100.00")
            assert db_a.override_price == Decimal("90.00")
            assert db_a.price_list_version_id == v1.id
            assert db_a.deleted_at is None
            # B: из последнего «чужого» снапшота (v1, не v0)
            db_b = await s.get(Product, b.id)
            assert db_b.base_price == Decimal("200.00")
            assert db_b.price_list_version_id == v1.id
            # C: soft-delete
            db_c = await s.get(Product, c.id)
            assert db_c.deleted_at is not None
            assert db_c.stock_status == StockStatus.ARCHIVED
            # аудит версии
            db_v = await s.get(PriceListVersion, v2.id)
            assert db_v.rolled_back_at is not None
            assert db_v.rolled_back_by == mgr.id
            # v0/v1 не тронуты
            assert (await s.get(PriceListVersion, v0.id)).rolled_back_at is None
            assert (await s.get(PriceListVersion, v1.id)).rolled_back_at is None

    async def test_archived_product_disappears_from_catalog(
        self, api_client, session_factory
    ):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        _v0, _v1, v2, _a, _b, _c = await _seed_two_versions(sf, manager=mgr)
        await _login(api_client, MANAGER_EMAIL)
        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 200, r.text

        await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)
        r = await api_client.get("/api/v1/catalog/products?per_page=50")
        assert r.status_code == 200, r.text
        skus = {row["sku"] for row in r.json()["data"]}
        assert "A-1" in skus and "B-2" in skus
        assert "C-3" not in skus


# ===========================================================================
# 2. Гварды: 409 / 404 / 403
# ===========================================================================
@pytest.mark.asyncio
class TestRollbackGuards:
    async def test_not_latest_done_version_409(self, api_client, session_factory):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        _v0, v1, v2, _a, _b, _c = await _seed_two_versions(sf, manager=mgr)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v1.id}/rollback")
        assert r.status_code == 409, r.text
        async with sf() as s:
            assert (await s.get(PriceListVersion, v1.id)).rolled_back_at is None

    async def test_double_rollback_409(self, api_client, session_factory):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        _v0, _v1, v2, _a, _b, _c = await _seed_two_versions(sf, manager=mgr)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 200, r.text
        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 409, r.text
        assert "уже откачена" in r.json()["detail"]

    @pytest.mark.parametrize(
        "status_",
        [
            PriceListVersionStatus.QUEUED,
            PriceListVersionStatus.PROCESSING,
            PriceListVersionStatus.FAILED,
        ],
    )
    async def test_not_done_status_409(self, api_client, session_factory, status_):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        v = await _make_version(sf, manager=mgr, status=status_)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v.id}/rollback")
        assert r.status_code == 409, r.text
        assert "DONE" in r.json()["detail"]

    async def test_unknown_version_404(self, api_client, session_factory):
        sf = session_factory
        await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        r = await api_client.post(f"/api/v1/manager/prices/versions/{uuid.uuid4()}/rollback")
        assert r.status_code == 404, r.text

    async def test_client_role_403(self, api_client, session_factory):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        _v0, _v1, v2, _a, _b, _c = await _seed_two_versions(sf, manager=mgr)
        await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 403, r.text
        async with sf() as s:
            assert (await s.get(PriceListVersion, v2.id)).rolled_back_at is None


# ===========================================================================
# 3. Кэш
# ===========================================================================
@pytest.mark.asyncio
class TestRollbackCache:
    async def test_invalidates_catalog_and_filters(
        self, api_client, session_factory, monkeypatch
    ):
        sf = session_factory
        mgr = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        _v0, _v1, v2, _a, _b, _c = await _seed_two_versions(sf, manager=mgr)
        await _login(api_client, MANAGER_EMAIL)

        calls: list[tuple[str, ...]] = []

        async def _invalidate(*tags):
            calls.append(tags)
            return 0

        monkeypatch.setattr(pli_service, "invalidate_tags", _invalidate)

        r = await api_client.post(f"/api/v1/manager/prices/versions/{v2.id}/rollback")
        assert r.status_code == 200, r.text
        assert calls == [(CATALOG_TAG, FILTERS_TAG)]
