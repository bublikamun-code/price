"""Тесты брендов и фото серий менеджера (/manager/brands, /series/{id}/photo).

См. §6, §16 п.20-3. CRUD брендов (авто-slug c суффиксом, стабильный slug при
переименовании, guard удаления 409), счётчики; загрузка фото серии — S3
замокан (как tests/test_photo_zip.py): webp large+thumb в photos-series.
"""
import io
import uuid
from datetime import datetime, timezone

from PIL import Image
from sqlalchemy import select

import app.api.v1.manager.brands as brands_api
from app.core.config import settings
from app.models.catalog import Brand, Product, Series
from app.models.enums import UserRole
from app.models.system import AuditLog
from app.services import storage
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


# ---------- helpers ----------

async def _login(api_client, email, password=PASSWORD):
    return await api_client.post("/api/v1/auth/login",
                                 json={"email": email, "password": password})


async def _login_manager(api_client, sf):
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER,
                                password=PASSWORD)
    r = await _login(api_client, MANAGER_EMAIL)
    assert r.status_code == 200, r.text
    return manager


def _png_bytes(size=(50, 30), color=(120, 140, 60)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------- RBAC
async def test_brands_require_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.get("/api/v1/manager/brands")).status_code == 403
    assert (
        await api_client.post("/api/v1/manager/brands", json={"name": "X"})
    ).status_code == 403


# ------------------------------------------------------------------ create
async def test_create_brand_autoslug_and_collision_suffix(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)

    r = await api_client.post("/api/v1/manager/brands", json={"name": "Nova Brand"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Nova Brand"
    assert body["slug"] == "nova-brand"
    assert body["series_count"] == 0 and body["products_count"] == 0

    # то же имя → коллизия slug → авто-суффиксы -2, -3
    r = await api_client.post("/api/v1/manager/brands", json={"name": "Nova Brand"})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "nova-brand-2"
    r = await api_client.post("/api/v1/manager/brands", json={"name": "Nova Brand"})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "nova-brand-3"

    # нормализация как в photo_zip._norm_stem: lower, ``_``/пробел → ``-``
    r = await api_client.post("/api/v1/manager/brands", json={"name": "Foo_Bar Q"})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "foo-bar-q"

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "brand.create")
        )).scalars().all()
    assert len(entries) == 4
    assert entries[0].actor_id == manager.id
    assert entries[0].target_type == "brand"
    assert entries[0].after["slug"] == "nova-brand"

    # пустое имя → 422
    r = await api_client.post("/api/v1/manager/brands", json={"name": "   "})
    assert r.status_code == 422, r.text


# ------------------------------------------------------- list / rename
async def test_list_brands_counts_and_rename_keeps_slug(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)
    alpha = await create_brand(sf, name="Alpha")
    await create_series(sf, brand=alpha, name="Serie X")
    await create_series(sf, brand=alpha, name="Serie Y")
    await create_product(sf, sku="A-1", name="Widget", brand=alpha)
    await create_product(sf, sku="A-2", name="Wadget", brand=alpha)
    gone = await create_product(sf, sku="A-3", name="Gone", brand=alpha)
    async with sf() as s:  # удалённый товар не считается
        db_product = await s.get(Product, gone.id)
        db_product.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    await create_brand(sf, name="Beta")

    r = await api_client.get("/api/v1/manager/brands")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["name"] for b in body] == ["Alpha", "Beta"]  # по имени
    by_name = {b["name"]: b for b in body}
    assert by_name["Alpha"]["series_count"] == 2
    assert by_name["Alpha"]["products_count"] == 2          # без deleted
    assert by_name["Beta"]["series_count"] == 0
    assert by_name["Beta"]["products_count"] == 0

    # переименование: slug не меняется (стабильные ключи фото)
    r = await api_client.patch(
        f"/api/v1/manager/brands/{alpha.id}", json={"name": "Alpha Renamed"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Alpha Renamed"
    assert body["slug"] == alpha.slug
    assert body["series_count"] == 2 and body["products_count"] == 2

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "brand.update")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].actor_id == manager.id
    assert entries[0].before == {"name": "Alpha"}
    assert entries[0].after == {"name": "Alpha Renamed"}

    # неизвестный бренд → 404
    assert (
        await api_client.patch(
            f"/api/v1/manager/brands/{uuid.uuid4()}", json={"name": "X"}
        )
    ).status_code == 404


# ------------------------------------------------------------------ delete
async def test_delete_brand_guards(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)

    # с серией → 409
    with_series = await create_brand(sf, name="With Series")
    await create_series(sf, brand=with_series, name="Serie X")
    r = await api_client.delete(f"/api/v1/manager/brands/{with_series.id}")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Нельзя удалить бренд, у которого есть серии или товары"

    # только с товарами → 409
    with_products = await create_brand(sf, name="With Products")
    await create_product(sf, sku="W-1", name="Widget", brand=with_products)
    r = await api_client.delete(f"/api/v1/manager/brands/{with_products.id}")
    assert r.status_code == 409, r.text

    # пустой бренд → 204, строка удалена
    empty = await create_brand(sf, name="Empty")
    r = await api_client.delete(f"/api/v1/manager/brands/{empty.id}")
    assert r.status_code == 204, r.text
    async with sf() as s:
        assert (await s.get(Brand, empty.id)) is None
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "brand.delete")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].target_id == empty.id
    assert entries[0].before == {"name": "Empty", "slug": "empty"}

    # неизвестный → 404
    assert (
        await api_client.delete(f"/api/v1/manager/brands/{uuid.uuid4()}")
    ).status_code == 404


# ------------------------------------------------------- фото серии (п.20-3)
async def test_series_photo_upload(api_client, session_factory, monkeypatch):
    sf = session_factory
    await _login_manager(api_client, sf)
    brand = await create_brand(sf, name="KEAZ")
    serie = await create_series(sf, brand=brand, name="Serie X")

    captured: list[dict] = []

    def _upload(bucket, key, fileobj, **kwargs):
        captured.append(
            {"bucket": bucket, "key": key, "body": fileobj.read(), "kwargs": kwargs}
        )

    monkeypatch.setattr(storage, "upload_fileobj", _upload)

    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("photo.jpg", io.BytesIO(_png_bytes()), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["photo_key"] == "photos-series/serie-x.webp"
    assert body["photo_url"] == "/api/v1/files/photo?key=photos-series/serie-x.webp"

    # два webp-объекта: large + thumb (ключ и content_type — как у photo-ZIP)
    assert {u["bucket"] for u in captured} == {settings.s3_bucket_photos}
    by_key = {u["key"]: u for u in captured}
    assert set(by_key) == {
        "photos-series/serie-x.webp",
        "photos-series/serie-x_thumb.webp",
    }
    for u in captured:
        assert u["kwargs"]["content_type"] == "image/webp"
        img = Image.open(io.BytesIO(u["body"]))
        assert img.format == "WEBP"
        if "_thumb" in u["key"]:
            assert img.size <= (400, 400)
        else:
            assert img.size == (50, 30)  # thumbnail не увеличивает

    async with sf() as s:
        assert (await s.get(Series, serie.id)).photo_key == "photos-series/serie-x.webp"

    # аудит мутации
    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "series.photo.update")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].target_id == serie.id
    assert entries[0].after == {"photo_key": "photos-series/serie-x.webp"}


async def test_series_photo_validation_errors(api_client, session_factory, monkeypatch):
    sf = session_factory
    await _login_manager(api_client, sf)
    brand = await create_brand(sf, name="KEAZ")
    serie = await create_series(sf, brand=brand, name="Serie X")

    captured: list[tuple] = []
    monkeypatch.setattr(storage, "upload_fileobj",
                        lambda *a, **k: captured.append(a))

    # не-изображение по расширению → 415
    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("photo.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 415, r.text

    # .jpg-имя, но содержимое не открывается Pillow → 415
    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("broken.jpg", io.BytesIO(b"not an image"), "image/jpeg")},
    )
    assert r.status_code == 415, r.text

    # неизвестная серия → 404 (проверяем до снижения лимита размера)
    r = await api_client.post(
        f"/api/v1/manager/series/{uuid.uuid4()}/photo",
        files={"file": ("photo.jpg", io.BytesIO(_png_bytes()), "image/jpeg")},
    )
    assert r.status_code == 404, r.text

    # >20 МБ → 413 (лимит занижен, как в tests/test_photo_zip.py)
    monkeypatch.setattr(brands_api, "_MAX_BYTES", 64)
    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("photo.jpg", io.BytesIO(b"x" * 200), "image/jpeg")},
    )
    assert r.status_code == 413, r.text

    assert captured == []  # ни одной загрузки в S3

    # клиент → 403 (RBAC-зависимость срабатывает до чтения файла)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("photo.jpg", io.BytesIO(_png_bytes()), "image/jpeg")},
    )
    assert r.status_code == 403, r.text


async def test_series_photo_oversize_real_limit(api_client, session_factory, monkeypatch):
    """Настоящий лимит 20 МБ: файл 20 МБ + 1 байт → 413 (валидный PNG-хвост
    не нужен — проверка размера идёт до Pillow)."""
    sf = session_factory
    await _login_manager(api_client, sf)
    brand = await create_brand(sf, name="KEAZ")
    serie = await create_series(sf, brand=brand, name="Serie X")

    captured: list[tuple] = []
    monkeypatch.setattr(storage, "upload_fileobj",
                        lambda *a, **k: captured.append(a))

    r = await api_client.post(
        f"/api/v1/manager/series/{serie.id}/photo",
        files={"file": ("photo.png", io.BytesIO(b"\x89PNG" + b"x" * (20 * 1024 * 1024)),
                        "image/png")},
    )
    assert r.status_code == 413, r.text
    assert captured == []
