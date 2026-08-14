"""Тесты CSV-импорта прайс-листа. См. ARCHITECTURE_PLAN.md §7, §16 п.3, §17.2.

Слои:
  1. Конвертер (чистый, без БД/S3): detect_separator / resolve_columns / normalize_row.
  2. Задача импорта (интеграция с БД, S3 замокан): upsert, конвертация валюты,
     override preserve, ARCHIVE_MISSING, PriceHistory, отчёт ошибок.
  3. Эндпоинт /manager/prices/* : RBAC, загрузка, список версий, отчёт ошибок.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

import app.tasks.import_price_list as import_task
import app.tasks.notifications as notif_task
from app.api.v1.manager import prices as prices_api
from app.importers.csv_price import (
    NormalizedRow,
    RowError,
    SchemaError,
    detect_separator,
    normalize_row,
    resolve_columns,
)
from app.models.catalog import PriceHistory, PriceListVersion, Product
from app.models.enums import (
    ImportMode,
    PriceListVersionStatus,
    StockStatus,
    UserRole,
)
from tests.conftest import create_product, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


# ---------- helpers ----------
async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _make_version(sf, *, manager, filename="p.csv", mode=ImportMode.UPSERT,
                        rate_to_byn=1, base_currency="BYN"):
    async with sf() as s:
        v = PriceListVersion(
            uploaded_by=manager.id,
            filename=filename,
            import_mode=mode,
            status=PriceListVersionStatus.QUEUED,
            base_currency=base_currency,
            rate_to_byn=rate_to_byn,
            rate_source="MANUAL",
        )
        s.add(v)
        await s.commit()
        await s.refresh(v)
        return v


def _patch_storage(monkeypatch, csv_bytes):
    """Мокаем S3: get_bytes отдаёт CSV, put_bytes (отчёт) — no-op."""
    monkeypatch.setattr(import_task.storage, "get_bytes", lambda b, k: csv_bytes)
    monkeypatch.setattr(import_task.storage, "put_bytes", lambda *a, **k: None)


# ===========================================================================
# 1. Конвертер (чистые unit-тесты)
# ===========================================================================
class TestConverter:
    def test_detect_separator(self):
        assert detect_separator("a;b;c") == ";"
        assert detect_separator("a,b,c") == ","
        assert detect_separator("a\tb\tc") == "\t"
        assert detect_separator("single") == ";"  # дефолт

    def test_resolve_columns_ru_and_en(self):
        cols = resolve_columns(["Артикул", "Наименование", "Бренд", "Цена"])
        assert cols["sku"] == "Артикул"
        assert cols["name"] == "Наименование"
        assert cols["brand"] == "Бренд"
        assert cols["base_price"] == "Цена"

        cols = resolve_columns(["sku", "name", "base_price"])
        assert set(cols) == {"sku", "name", "base_price"}

    def test_resolve_columns_strips_bom_and_case(self):
        cols = resolve_columns(["\ufeffАртикул", "НАИМЕНОВАНИЕ"])
        assert "sku" in cols and "name" in cols

    def test_resolve_columns_missing_required(self):
        with pytest.raises(SchemaError):
            resolve_columns(["Бренд"])  # нет sku / name


class TestNormalizeRow:
    def _ok(self, row, n=2):
        r = normalize_row(row, n)
        assert isinstance(r, NormalizedRow), r
        return r

    def test_valid_ru_with_comma_decimal(self):
        r = self._ok({
            "sku": "OB-12", "name": "Корпус 12", "brand": "KEAZ",
            "base_price": "29,60", "discount_price": "27,00",
            "stock_status": "В наличии",
        })
        assert r.sku == "OB-12"
        assert r.base_price == Decimal("29.6")
        assert r.discount_price == Decimal("27.0")
        assert r.stock_status == StockStatus.IN_STOCK
        assert r.brand == "KEAZ"

    def test_default_brand_and_optional_fields(self):
        r = self._ok({"sku": "A-1", "name": "Widget", "base_price": "10"})
        assert r.brand == "Прочее"
        assert r.series is None
        assert r.discount_price is None
        assert r.stock_status == StockStatus.IN_STOCK

    def test_stock_preorder_ru(self):
        r = self._ok({"sku": "A", "name": "N", "base_price": "1",
                      "stock_status": "под заказ"})
        assert r.stock_status == StockStatus.PREORDER

    def test_missing_sku(self):
        assert isinstance(normalize_row({"name": "N", "base_price": "1"}, 2), RowError)

    def test_missing_name(self):
        assert isinstance(normalize_row({"sku": "A", "base_price": "1"}, 2), RowError)

    def test_bad_price(self):
        res = normalize_row({"sku": "A", "name": "N", "base_price": "abc"}, 2)
        assert isinstance(res, RowError)
        assert res.column == "base_price"

    def test_zero_or_negative_price(self):
        for bad in ("0", "-5"):
            res = normalize_row({"sku": "A", "name": "N", "base_price": bad}, 2)
            assert isinstance(res, RowError)

    def test_bad_discount(self):
        res = normalize_row({"sku": "A", "name": "N", "base_price": "1",
                             "discount_price": "xyz"}, 2)
        assert isinstance(res, RowError)
        assert res.column == "discount_price"


# ===========================================================================
# 2. Задача импорта (БД + замоканный S3)
# ===========================================================================
@pytest.mark.asyncio
class TestImportTask:
    @pytest.fixture(autouse=True)
    def _mock_dispatch(self, monkeypatch):
        """Импорт триггерит dispatch_price_changed (§20.4) — мокаем .delay,
        чтобы не звать Celery-брокер в тестах импорта."""
        monkeypatch.setattr(notif_task.dispatch_price_changed, "delay", lambda vid: None)

    async def test_import_invalidates_catalog_and_filters(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(session_factory, manager=mgr)
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, b"sku;name;base_price\nC-1;Cached;10\n")
        calls = []

        async def _invalidate(*tags):
            calls.append(tags)
            return 0

        monkeypatch.setattr(import_task, "invalidate_tags", _invalidate)
        await import_task._run_import(version.id)
        assert calls == [("catalog", "filters")]

    async def test_upsert_and_currency_conversion(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(session_factory, manager=mgr,
                                      rate_to_byn=3, base_currency="USD")
        csv = b"sku;name;brand;base_price\nA-1;Widget;KEAZ;10\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            v = await s.get(PriceListVersion, version.id)
            assert v.status == PriceListVersionStatus.DONE
            assert v.rows_ok == 1
            assert v.rows_total == 1
            assert v.rows_error == 0
            prod = (await s.execute(
                select(Product).where(Product.sku == "A-1")
            )).scalar_one()
            assert prod.base_price == Decimal("30.00")  # 10 USD * 3
            ph = (await s.execute(
                select(PriceHistory).where(PriceHistory.product_id == prod.id)
            )).scalars().all()
            assert len(ph) == 1
            assert ph[0].base_price == Decimal("30.00")

    async def test_override_preserved_without_discount(self, session_factory, monkeypatch):
        """CSV без discount_price не должен затирать override_price менеджера (§16 п.3)."""
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await create_product(session_factory, sku="A-2", name="Old", base_price=100,
                             override_price=Decimal("50.00"))
        version = await _make_version(session_factory, manager=mgr)
        csv = b"sku;name;base_price\nA-2;Updated;9\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            prod = (await s.execute(
                select(Product).where(Product.sku == "A-2")
            )).scalar_one()
            assert prod.name == "Updated"
            assert prod.base_price == Decimal("9.00")
            assert prod.override_price == Decimal("50.00")  # сохранён

    async def test_override_updated_with_discount(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await create_product(session_factory, sku="A-3", name="Old", base_price=100,
                             override_price=Decimal("50.00"))
        version = await _make_version(session_factory, manager=mgr)
        csv = b"sku;name;base_price;discount_price\nA-3;Updated;100;42\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            prod = (await s.execute(
                select(Product).where(Product.sku == "A-3")
            )).scalar_one()
            assert prod.override_price == Decimal("42")

    async def test_discount_converted_to_byn(self, session_factory, monkeypatch):
        """discount_price в валюте CSV → BYN по rate_to_byn (§17.2)."""
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(session_factory, manager=mgr,
                                      rate_to_byn=3, base_currency="USD")
        csv = b"sku;name;base_price;discount_price\nD-1;X;10;8\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            prod = (await s.execute(
                select(Product).where(Product.sku == "D-1")
            )).scalar_one()
            assert prod.base_price == Decimal("30.00")     # 10 USD * 3
            assert prod.override_price == Decimal("24.00")  # 8 USD * 3

    async def test_row_errors_collected(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(session_factory, manager=mgr)
        # 2-я строка без цены, 3-я ок.
        csv = b"sku;name;base_price\nA;N;1\nB;M;\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            v = await s.get(PriceListVersion, version.id)
            assert v.status == PriceListVersionStatus.DONE
            assert v.rows_ok == 1
            assert v.rows_error == 1
            assert v.rows_total == 2
            # файл с ошибкой записан в S3 (замокан), ключ сохранён
            assert v.error_log_key == f"{version.id}.csv"

    async def test_archive_missing(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await create_product(session_factory, sku="OLD-1", name="Stale", base_price=10)
        version = await _make_version(session_factory, manager=mgr,
                                      mode=ImportMode.ARCHIVE_MISSING)
        csv = b"sku;name;base_price\nNEW-1;Fresh;5\n"
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, csv)

        await import_task._run_import(version.id)

        async with session_factory() as s:
            stale = (await s.execute(
                select(Product).where(Product.sku == "OLD-1")
            )).scalar_one()
            assert stale.deleted_at is not None
            assert stale.stock_status == StockStatus.ARCHIVED
            fresh = (await s.execute(
                select(Product).where(Product.sku == "NEW-1")
            )).scalar_one()
            assert fresh.deleted_at is None

    async def test_idempotent_skip_when_not_queued(self, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        version = await _make_version(session_factory, manager=mgr)
        async with session_factory() as s:
            v = await s.get(PriceListVersion, version.id)
            v.status = PriceListVersionStatus.DONE
            await s.commit()
        monkeypatch.setattr(import_task, "_worker_session", session_factory)
        _patch_storage(monkeypatch, b"sku;name;base_price\nA;N;1\n")

        res = await import_task._run_import(version.id)
        assert res["status"] == "skipped"


# ===========================================================================
# 3. Эндпоинт /manager/prices/*
# ===========================================================================
@pytest.mark.asyncio
class TestPricesEndpoint:
    async def test_upload_manager_202(self, api_client, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        called = {}
        monkeypatch.setattr(prices_api.run_import, "delay", lambda vid: called.setdefault("vid", vid))
        monkeypatch.setattr(prices_api.storage, "put_bytes", lambda *a, **k: None)

        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={"file": ("p.csv", b"sku;name;base_price\nA;N;1\n", "text/csv")},
            data={"mode": "UPSERT", "base_currency": "BYN", "rate_to_byn": "1"},
        )
        assert r.status_code == 202, r.text
        vid = r.json()["version_id"]
        assert called.get("vid") == vid

        async with session_factory() as s:
            v = await s.get(PriceListVersion, uuid.UUID(vid))
            assert v is not None
            assert v.status == PriceListVersionStatus.QUEUED
            assert v.rate_source == "MANUAL"
            assert v.uploaded_by == mgr.id

    async def test_upload_forbidden_for_client(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)
        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={"file": ("p.csv", b"sku;name;base_price\nA;N;1\n", "text/csv")},
            data={"mode": "UPSERT"},
        )
        assert r.status_code == 403

    async def test_upload_requires_auth(self, api_client):
        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={"file": ("p.csv", b"sku;name;base_price\nA;N;1\n", "text/csv")},
            data={"mode": "UPSERT"},
        )
        assert r.status_code == 401

    async def test_upload_rejects_wrong_extension(self, api_client, session_factory, monkeypatch):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        monkeypatch.setattr(prices_api.storage, "put_bytes", lambda *a, **k: None)
        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={"file": ("p.xlsx", b"bytes", "application/octet-stream")},
            data={"mode": "UPSERT"},
        )
        assert r.status_code == 415

    @pytest.mark.parametrize(
        ("content", "content_type", "expected_status"),
        [
            (b"sku;name;base_price\nA;N;1\n", "image/png", 415),
            (b"\x89PNG\x00binary", "text/csv", 415),
            (b"\xff\xfebad", "text/csv", 415),
            (b"brand;base_price\nB;1\n", "text/csv", 422),
        ],
    )
    async def test_upload_rejects_invalid_csv_content(
        self, api_client, session_factory, monkeypatch, content, content_type, expected_status
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        stored = []
        monkeypatch.setattr(prices_api.storage, "put_bytes", lambda *a, **k: stored.append(a))

        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={"file": ("p.csv", content, content_type)},
            data={"mode": "UPSERT"},
        )

        assert r.status_code == expected_status
        assert stored == []

    async def test_upload_accepts_utf8_bom_and_generic_mime(
        self, api_client, session_factory, monkeypatch
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        monkeypatch.setattr(prices_api.run_import, "delay", lambda vid: None)
        monkeypatch.setattr(prices_api.storage, "put_bytes", lambda *a, **k: None)

        r = await api_client.post(
            "/api/v1/manager/prices/import",
            files={
                "file": (
                    "p.csv",
                    "\ufeffАртикул;Наименование;Цена\nA;N;1\n".encode(),
                    "application/octet-stream",
                )
            },
            data={"mode": "UPSERT"},
        )

        assert r.status_code == 202, r.text

    async def test_list_and_get_version(self, api_client, session_factory):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        v = await _make_version(session_factory, manager=mgr)

        r = await api_client.get("/api/v1/manager/prices/versions")
        assert r.status_code == 200
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == str(v.id)

        r = await api_client.get(f"/api/v1/manager/prices/versions/{v.id}")
        assert r.status_code == 200
        assert r.json()["filename"] == "p.csv"

        # неизвестная версия → 404
        r = await api_client.get(
            f"/api/v1/manager/prices/versions/{uuid.uuid4()}"
        )
        assert r.status_code == 404

    async def test_errors_endpoint(self, api_client, session_factory, monkeypatch):
        mgr = await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        v = await _make_version(session_factory, manager=mgr)

        # Нет error_log_key → 404
        r = await api_client.get(f"/api/v1/manager/prices/versions/{v.id}/errors")
        assert r.status_code == 404

        # Есть error_log_key → presigned URL
        async with session_factory() as s:
            db_v = await s.get(PriceListVersion, v.id)
            db_v.error_log_key = f"{v.id}.csv"
            await s.commit()
        monkeypatch.setattr(prices_api.storage, "presigned_get",
                            lambda b, k, **kw: "http://minio.local/presigned")
        r = await api_client.get(f"/api/v1/manager/prices/versions/{v.id}/errors")
        assert r.status_code == 200
        assert r.json()["url"].startswith("http://minio.local")
