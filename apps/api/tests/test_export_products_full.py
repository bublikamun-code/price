"""Тесты полного экспорта продукции в CSV (менеджер): характеристики колонками
+ ссылки на фото отдельными колонками.

Слои:
  1. build_table (чистый): базовые колонки + объединение ключей attributes
     (sorted) + «Фото N»; главное фото — личное, иначе фото серии.
  2. Пайплайн задачи (интеграция с БД, S3 замокан): CSV utf-8-sig/``;``,
     галереи фото одним запросом, удалённые товары исключены.
  3. Эндпоинт /manager/products/export: RBAC (клиенту — 403), 202 + job_id.
"""
import csv
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import update

import app.services.product_export as product_export
import app.tasks.export_products_full as export_task
from app.models.catalog import Product, ProductPhoto
from app.models.enums import StockStatus, UserRole
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


def _parse_csv(body: bytes):
    """CSV выгрузки → строки [[cell, …], …] с учётом BOM и разделителя ``;``."""
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig")), delimiter=";"))


def _product(**kwargs):
    defaults = dict(
        sku="SKU-1", name="Товар", base_price="100.00", override_price=None,
        stock_status=StockStatus.IN_STOCK, stock_qty=None, attributes={},
    )
    return SimpleNamespace(id=uuid.uuid4(), **{**defaults, **kwargs})


def _catalog_row(product, *, brand_name=None, series_name=None,
                 series_photo_key=None):
    """Заглушка строки результата join-запроса: ``row[0]`` — товар,
    остальное — named-атрибуты (как у SQLAlchemy Row)."""

    class _Row:
        def __init__(self):
            self.brand_name = brand_name
            self.series_name = series_name
            self.series_photo_key = series_photo_key

        def __getitem__(self, idx):
            return (product,)[idx]

    return _Row()


def _states_stub(states: list):
    async def _set(job_id, **fields):
        states.append(fields)

    return _set


# ---------- 1. build_table (чистый) ----------

class TestBuildTable:
    def test_columns_union_of_attributes_and_photos(self):
        rows = [
            _catalog_row(_product(sku="A-1", name="Щит", base_price="10.00",
                                  stock_qty=1,
                                  attributes={"цвет": "белый", "ip": "IP54"}),
                         brand_name="Бренд", series_name="Серия"),
            _catalog_row(_product(sku="B-1", name="Автомат", base_price="20.50",
                                  override_price="18.00",
                                  stock_status=StockStatus.PREORDER,
                                  attributes={"полюса": 2})),
        ]
        columns, records = export_task.build_table(rows, {})

        # Базовые + объединение ключей attributes (sorted: латиница < кириллица);
        # фото ни у кого нет — фото-колонок нет.
        assert columns == export_task.BASE_COLUMNS + ["ip", "полюса", "цвет"]
        assert len(records) == 2
        # Первая строка: пустая ячейка чужой характеристики, цены с 2 знаками.
        assert records[0][:8] == ["A-1", "Щит", "Бренд", "Серия", "IN_STOCK",
                                  "1", "10.00", ""]
        assert records[0][8:] == ["IP54", "", "белый"]
        # Вторая строка: override-цена, пустой остаток и бренд/серия.
        assert records[1][:8] == ["B-1", "Автомат", "", "", "PREORDER",
                                  "", "20.50", "18.00"]
        assert records[1][8:] == ["", "2", ""]

    def test_photo_columns_and_series_fallback(self, monkeypatch):
        monkeypatch.setattr(export_task.settings, "web_app_url",
                            "https://portal.example.by")
        p1 = _product(sku="P-1", name="С фото")
        p2 = _product(sku="P-2", name="Без фото")
        rows = [
            _catalog_row(p1),
            _catalog_row(p2, series_name="S", series_photo_key="photos-series/s.webp"),
        ]
        photos = {p1.id: [f"photos-product/{p1.id}/aaaaaaaa.webp",
                          f"photos-product/{p1.id}/bbbbbbbb.webp"]}
        columns, records = export_task.build_table(rows, photos)

        assert columns[-2:] == ["Фото 1", "Фото 2"]
        assert records[0][-2] == (
            "https://portal.example.by/api/v1/public/photo?key="
            f"photos-product%2F{p1.id}%2Faaaaaaaa.webp"
        )
        # У второго товара нет галереи — подставляется фото серии, Фото 2 пусто.
        assert records[1][-2] == (
            "https://portal.example.by/api/v1/public/photo?key=photos-series%2Fs.webp"
        )
        assert records[1][-1] == ""

    def test_nested_attribute_value_serialized_as_json(self):
        p = _product(attributes={"габариты": {"в": 100, "ш": 50}})
        columns, records = export_task.build_table([_catalog_row(p)], {})
        assert columns[-1] == "габариты"
        assert records[0][-1] == '{"в": 100, "ш": 50}'


# ---------- 2. Пайплайн задачи (интеграция с БД) ----------

class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_export_csv(self, session_factory, monkeypatch):
        manager = await create_user(session_factory, email=MANAGER_EMAIL,
                                    role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="IEK")
        series = await create_series(session_factory, brand=brand, name="Серия A",
                                     photo_key="photos-series/a.webp")
        p1 = await create_product(
            session_factory, sku="SKU-1", name="Выключатель", brand=brand,
            series=series, base_price=12.5, override_price=10,
            stock=StockStatus.IN_STOCK, stock_qty=7,
            attributes={"цвет": "белый"},
        )
        await create_product(
            session_factory, sku="SKU-2", name="Розетка", brand=brand,
            series=series, base_price=20, stock=StockStatus.PREORDER,
            attributes={"полюса": 2},
        )
        deleted = await create_product(
            session_factory, sku="SKU-DEL", name="Удалённый", brand=brand,
            base_price=1, stock=StockStatus.IN_STOCK,
        )
        async with session_factory() as s:
            await s.execute(
                update(Product).where(Product.id == deleted.id)
                .values(deleted_at=datetime(2026, 1, 1, tzinfo=UTC))
            )
            s.add(ProductPhoto(
                product_id=p1.id,
                photo_key=f"photos-product/{p1.id}/11111111.webp",
                sort_order=0,
            ))
            await s.commit()

        monkeypatch.setattr(export_task, "_worker_session", session_factory)

        uploaded: dict[str, bytes] = {}
        monkeypatch.setattr(
            export_task.storage, "upload_fileobj",
            lambda bucket, key, buf, content_type=None: uploaded.update(
                {key: buf.getvalue()}
            ),
        )
        states: list[dict] = []
        monkeypatch.setattr(product_export, "set_job_state", _states_stub(states))

        job_id = uuid.uuid4()
        result = await export_task._run_full_export(job_id, manager.id)

        assert result["status"] == "DONE"
        assert states[-1]["status"] == "DONE"
        assert list(uploaded) == [f"export/products-full-{job_id}.csv"]

        parsed = _parse_csv(uploaded[f"export/products-full-{job_id}.csv"])
        header, rows = parsed[0], parsed[1:]
        assert header[:8] == export_task.BASE_COLUMNS
        assert header[8:] == ["полюса", "цвет", "Фото 1"]
        assert len(rows) == 2  # удалённых товаров в выгрузке нет

        by_sku = {r[0]: r for r in rows}
        r1 = by_sku["SKU-1"]
        assert r1[4] == "IN_STOCK" and r1[5] == "7"
        assert r1[6] == "12.50" and r1[7] == "10.00"
        assert r1[header.index("цвет")] == "белый"
        assert r1[header.index("Фото 1")].endswith(
            f"public/photo?key=photos-product%2F{p1.id}%2F11111111.webp"
        )
        r2 = by_sku["SKU-2"]
        # Галереи нет — фото серии; override/остаток пустые.
        assert r2[5] == "" and r2[7] == ""
        assert "photos-series%2Fa.webp" in r2[header.index("Фото 1")]

    @pytest.mark.asyncio
    async def test_empty_catalog_exports_header_only(self, session_factory,
                                                     monkeypatch):
        manager = await create_user(session_factory, email=MANAGER_EMAIL,
                                    role=UserRole.MANAGER)
        monkeypatch.setattr(export_task, "_worker_session", session_factory)
        monkeypatch.setattr(export_task.storage, "upload_fileobj",
                            lambda *a, **k: None)
        monkeypatch.setattr(product_export, "set_job_state",
                            _states_stub([]))

        result = await export_task._run_full_export(uuid.uuid4(), manager.id)
        assert result["rows"] == 0


# ---------- 3. Эндпоинт /manager/products/export ----------

async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_client_forbidden(self, session_factory, api_client):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)
        r = await api_client.post("/api/v1/manager/products/export")
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_starts_job(self, session_factory, api_client,
                                      monkeypatch):
        manager = await create_user(session_factory, email=MANAGER_EMAIL,
                                    role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        # Сервис старта стабаем: контракт роутера — 202 и job_id из сервиса.
        async def _fake_start(*, user):
            assert user.id == manager.id
            return "00000000-0000-0000-0000-0000000000ab"

        monkeypatch.setattr(product_export, "start_full_export", _fake_start)

        r = await api_client.post("/api/v1/manager/products/export")
        assert r.status_code == 202, r.text
        assert r.json() == {"job_id": "00000000-0000-0000-0000-0000000000ab"}
