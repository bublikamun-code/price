"""API v2 media resources. См. ARCHITECTURE_PLAN.md §16 п.37,
docs/NATIVE_API_CONTRACT.md §6.1.

Смысл проверок: нативный клиент кэширует картинку по стабильному id, поэтому
    - id обязан быть детерминированным и не зависеть от времени жизни подписи;
    - наружу не должен утекать S3-ключ;
    - 404 на неизвестный id, а не 500.
"""
import uuid

import pytest

from app.models.enums import UserRole
from app.services import media as media_service
from app.services import storage
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
EMAIL = "media@example.by"
SERIES_KEY = "photos-series/serie-a.webp"
SERIES_THUMB = "photos-series/serie-a_thumb.webp"
PRODUCT_KEY = "photos-product/11111111-1111-4111-8111-111111111111/ab12cd34.webp"


@pytest.fixture
def stored_bytes(monkeypatch):
    """Подменяет чтение объекта: эндпоинт отдаёт байты, а не редирект."""
    requested: list[str] = []
    monkeypatch.setattr(
        "app.services.storage.get_bytes",
        lambda bucket, key, **kw: requested.append(key) or b"webp-bytes",
    )
    stored_bytes.requested = requested
    return stored_bytes


async def _login(api_client):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _client(session_factory):
    return await create_user(session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD)


# =========================================================
# Детерминированность идентификатора
# =========================================================
def test_media_id_is_uuid5_of_s3_key_and_stable():
    first = media_service.media_id_for_key(SERIES_KEY)
    assert first == media_service.media_id_for_key(SERIES_KEY)
    assert first != media_service.media_id_for_key(SERIES_THUMB)
    # Детерминирован по построению: смена константы namespace осиротила бы все
    # ранее выданные id, поэтому значение фиксировано в коде, а не в настройках.
    assert str(media_service.MEDIA_NAMESPACE) == "6f2c4a1e-7b3d-4c58-9a10-5d8e2f4b6c93"


def test_media_id_ignores_case_of_non_key_text():
    """Ключ — это ключ: два разных ключа не должны схлопываться в один id."""
    assert media_service.media_id_for_key("photos-series/a.webp") != media_service.media_id_for_key(
        "photos-series/b.webp"
    )


def test_dimensions_follow_importer_convention():
    assert media_service.dimensions_for_key(SERIES_THUMB) == (400, 400)
    assert media_service.dimensions_for_key(SERIES_KEY) == (1200, 1200)


def test_non_photo_key_is_rejected():
    assert media_service.is_photo_key(SERIES_KEY) is True
    assert media_service.is_photo_key("brands/catalog.pdf") is False


# =========================================================
# Реестр
# =========================================================
async def test_register_key_is_idempotent(session_factory):
    from sqlalchemy import func, select

    from app.models.file import MediaAsset

    async with session_factory() as s:
        first = await media_service.register_key(s, SERIES_KEY, commit=True)
        second = await media_service.register_key(s, SERIES_KEY, commit=True)
        assert first.id == second.id
        count = await s.scalar(
            select(func.count())
            .select_from(MediaAsset)
            .where(MediaAsset.s3_key == SERIES_KEY)
        )
        assert count == 1


async def test_register_key_rejects_non_photo_key(session_factory):
    async with session_factory() as s:
        with pytest.raises(ValueError):
            await media_service.register_key(s, "brands/catalog.pdf")


async def test_backfill_registers_series_and_product_photos(session_factory):
    brand = await create_brand(session_factory, name="Media Brand")
    series = await create_series(session_factory, brand=brand, name="Serie A", photo_key=SERIES_KEY)
    await create_product(session_factory, sku="MEDIA-1", name="Widget", brand=brand, series=series)

    from sqlalchemy import select

    from app.models.file import MediaAsset

    async with session_factory() as s:
        assert await media_service.register_existing_photo_keys(s) == 1
        # Второй прогон ничего не добавляет — миграция должна быть безопасна
        # при повторном применении.
        assert await media_service.register_existing_photo_keys(s) == 0
        row = await s.scalar(select(MediaAsset).where(MediaAsset.s3_key == SERIES_KEY))
        assert row is not None
        assert row.id == media_service.media_id_for_key(SERIES_KEY)
        assert (row.width, row.height) == (1200, 1200)
        assert row.mime_type == "image/webp"


# =========================================================
# Эндпоинт
# =========================================================
async def test_media_endpoint_returns_image_bytes(
    api_client, session_factory, stored_bytes
):
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)
        media_id = asset.id

    r = await api_client.get(f"/api/v2/media/{media_id}")
    assert r.status_code == 200, r.text
    # Байты отдаёт сам API: редирект на presigned здесь резался бы браузером
    # как mixed content (внешний S3-хост — http, портал — https).
    assert "location" not in r.headers
    assert r.content == b"webp-bytes"
    assert stored_bytes.requested == [SERIES_KEY]
    assert r.headers["content-type"].startswith("image/webp")
    # S3-ключ не должен утекать в тело ответа или в заголовки.
    assert SERIES_KEY.encode() not in r.content
    assert "photos-series" not in str(dict(r.headers))


async def test_media_url_is_stable_across_requests(
    api_client, session_factory, monkeypatch
):
    """Один и тот же URL отдаёт одно и то же — ради этого всё затевалось."""
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)
        media_id = asset.id

    monkeypatch.setattr(
        "app.services.storage.get_bytes", lambda b, k, **kw: b"first"
    )
    first = await api_client.get(f"/api/v2/media/{media_id}")
    monkeypatch.setattr(
        "app.services.storage.get_bytes", lambda b, k, **kw: b"second"
    )
    second = await api_client.get(f"/api/v2/media/{media_id}")

    assert first.content != second.content
    # А идентификатор, по которому клиент кэширует, не изменился.
    assert first.status_code == second.status_code == 200


async def test_media_missing_object_is_404(api_client, session_factory, monkeypatch):
    """Ключ есть в реестре, фото из бакета удалили → 404, а не 502."""
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)
        media_id = asset.id

    def _missing(bucket, key, **kw):
        raise storage.ObjectNotFound(f"нет {key}")

    monkeypatch.setattr("app.services.storage.get_bytes", _missing)
    r = await api_client.get(f"/api/v2/media/{media_id}")
    assert r.status_code == 404
    assert r.json()["code"] == "MEDIA_NOT_FOUND"


async def test_media_unknown_id_is_404_problem(api_client, session_factory, stored_bytes):
    await _client(session_factory)
    await _login(api_client)
    r = await api_client.get(f"/api/v2/media/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "MEDIA_NOT_FOUND"


async def test_media_requires_authentication(api_client, session_factory, stored_bytes):
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)
        media_id = asset.id
    r = await api_client.get(f"/api/v2/media/{media_id}")
    assert r.status_code == 401


async def test_media_malformed_id_is_validation_problem(api_client, session_factory, stored_bytes):
    await _client(session_factory)
    await _login(api_client)
    r = await api_client.get("/api/v2/media/not-a-uuid")
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


async def test_media_storage_failure_is_502(api_client, session_factory, monkeypatch):
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)
        media_id = asset.id

    def _boom(bucket, key, **kw):
        raise storage.StorageError("minio недоступен")

    monkeypatch.setattr("app.services.storage.get_bytes", _boom)
    r = await api_client.get(f"/api/v2/media/{media_id}")
    assert r.status_code == 502
    assert r.json()["code"] == "STORAGE_UNAVAILABLE"


# =========================================================
# Каталог отдаёт media, а не S3-ключи
# =========================================================
async def test_catalog_thumbnail_is_stable_media_ref(
    api_client, session_factory, stored_bytes
):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Media Brand")
    series = await create_series(session_factory, brand=brand, name="Serie A", photo_key=SERIES_THUMB)
    await create_product(
        session_factory, sku="MEDIA-1", name="Widget", brand=brand, series=series
    )
    await _login(api_client)

    r = await api_client.get("/api/v2/catalog/products")
    assert r.status_code == 200
    thumb = r.json()["data"][0]["thumbnail"]
    assert thumb["id"] == str(media_service.media_id_for_key(SERIES_THUMB))
    assert thumb["url"] == f"/api/v2/media/{media_service.media_id_for_key(SERIES_THUMB)}"
    assert (thumb["width"], thumb["height"]) == (400, 400)
    assert thumb["mimeType"] == "image/webp"
    # Ключ хранилища наружу не отдаётся ни в каком виде.
    assert SERIES_THUMB not in r.text
    assert "photos-series" not in r.text
    # Список отдаёт только плитку, без галереи.
    assert r.json()["data"][0]["media"] == []


async def test_product_detail_carries_gallery(api_client, session_factory, stored_bytes):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Media Brand")
    series = await create_series(session_factory, brand=brand, name="Serie A")
    product = await create_product(
        session_factory, sku="MEDIA-1", name="Widget", brand=brand, series=series
    )
    from app.models.catalog import ProductPhoto

    async with session_factory() as s:
        s.add(ProductPhoto(product_id=product.id, photo_key=PRODUCT_KEY))
        await s.commit()

    await _login(api_client)
    r = await api_client.get(f"/api/v2/catalog/products/{product.id}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["sku"] == "MEDIA-1"
    assert [m["id"] for m in data["media"]] == [
        str(media_service.media_id_for_key(PRODUCT_KEY))
    ]
    assert "photos-product" not in r.text


async def test_product_without_photo_has_null_thumbnail(
    api_client, session_factory, stored_bytes
):
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Media Brand")
    await create_product(session_factory, sku="BARE-1", name="No Photo", brand=brand)
    await _login(api_client)

    r = await api_client.get("/api/v2/catalog/products")
    assert r.json()["data"][0]["thumbnail"] is None


async def test_product_photo_wins_over_series_photo(
    api_client, session_factory, stored_bytes
):
    """Приоритет личного фото товара над фото серии — как в v1 (repositories/catalog.py)."""
    await _client(session_factory)
    brand = await create_brand(session_factory, name="Media Brand")
    series = await create_series(session_factory, brand=brand, name="Serie A", photo_key=SERIES_KEY)
    product = await create_product(
        session_factory, sku="MEDIA-2", name="Widget", brand=brand, series=series
    )
    from app.models.catalog import ProductPhoto

    async with session_factory() as s:
        s.add(ProductPhoto(product_id=product.id, photo_key=PRODUCT_KEY, sort_order=0))
        await s.commit()

    await _login(api_client)
    r = await api_client.get(f"/api/v2/catalog/products/{product.id}")
    thumb = r.json()["data"]["thumbnail"]
    assert thumb["id"] == str(media_service.media_id_for_key(PRODUCT_KEY))


# =========================================================
# Backfill в миграции 0020


def _load_migration_module():
    """Модуль миграции по пути: alembic-версии не лежат в импортируемом пакете."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0020_media_assets.py"
    spec = importlib.util.spec_from_file_location("mig_0020_media_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_backfill_derives_the_same_ids_as_the_service():
    """Id из backfill должен совпадать с id, который отдаёт рантайм.

    Миграция намеренно не импортирует app.services.media (она должна пережить
    правку приложения), поэтому расхождение namespace или формулы даст клиентам
    id, которые не резолвятся ни в один S3-ключ, — и это не поймает ни один
    другой тест, потому что registry и рантайм считают id разными функциями.
    """
    migration = _load_migration_module()
    keys = [SERIES_KEY, SERIES_THUMB, PRODUCT_KEY, SERIES_KEY, "", "brands/logo.webp"]
    rows = migration._backfill_rows(keys)
    by_key = {row["s3_key"]: row for row in rows}

    # Дубликат схлопнут, пустой ключ и не-photo префикс отброшены.
    assert set(by_key) == {SERIES_KEY, SERIES_THUMB, PRODUCT_KEY}

    for key, row in by_key.items():
        assert row["id"] == media_service.media_id_for_key(key)
        assert row["mime_type"] == "image/webp"

    assert (by_key[SERIES_THUMB]["width"], by_key[SERIES_THUMB]["height"]) == (400, 400)
    assert (by_key[SERIES_KEY]["width"], by_key[SERIES_KEY]["height"]) == (1200, 1200)
    assert (by_key[PRODUCT_KEY]["width"], by_key[PRODUCT_KEY]["height"]) == (1200, 1200)
