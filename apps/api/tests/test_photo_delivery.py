"""Выдача фото и реестр медиа: fail-closed и самовосстановление.

Проверяем поведение, важное для каталога и карточки товара:

  * ``GET /api/v1/files/photo`` отдаёт объект ТОЛЬКО если ключ известен
    системе (реестр файлов, реестр медиа каталога, таблица баннеров). Раньше
    проверка была fail-open: ключ, которого нет в ``file_assets``, всё равно
    читался из бакета — минуя visibility (MANAGER_ONLY);
  * каталог сам регистрирует недостающие ключи в реестре медиа: id фото —
    это uuid5 от S3-ключа, «развернуть» его обратно нельзя, и незарегистрированный
    ключ давал бы 404 на карточке;
  * «сырое» имя файла из CSV (не S3-ключ) наружу не отдаётся — объекта с таким
    именем в бакете нет, клиент показал бы битую картинку вместо заглушки;
  * конвенция thumb-ключа одна на всех и не ломается на составных ключах.
"""
import io
import uuid

import pytest
from PIL import Image

from app.models.banner import Banner
from app.models.catalog import ProductPhoto
from app.models.enums import BannerPosition, UserRole
from app.services import media as media_service
from app.services import storage
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
EMAIL = "photo@example.by"
SERIES_KEY = "photos-series/serie-a.webp"
PRODUCT_KEY = "photos-product/11111111-1111-4111-8111-111111111111/ab12cd34.webp"


@pytest.fixture(autouse=True)
def _clear_dimensions_cache():
    """Сброс кэша замеров: ключи из разных тестов не должны делить замер."""
    media_service._dimension_cache.clear()
    yield
    media_service._dimension_cache.clear()


def _png_bytes(size: tuple[int, int]) -> bytes:
    """PNG заданного размера — реальное изображение для замера геометрии."""
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def stored_objects(monkeypatch):
    """Подменяет чтение объекта из S3 для замера размеров.

    Отдельно от ``stored_bytes``: там байты произвольные («webp-bytes»), а
    здесь нужен настоящий кадр, чтобы Pillow смог прочитать геометрию.
    """
    objects: dict[str, bytes] = {}

    def _get_object_bytes(bucket: str, key: str) -> bytes:
        if key not in objects:
            raise storage.ObjectNotFound(f"нет {key}")
        return objects[key]

    monkeypatch.setattr(storage, "get_object_bytes", _get_object_bytes)
    return objects


@pytest.fixture
def stored_bytes(monkeypatch):
    """Подменяет чтение объекта из S3 (в тестах бакета нет)."""
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
    return await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )


# =========================================================
# Fail-closed выдача фото
# =========================================================
async def test_photo_endpoint_404_for_unknown_key(
    api_client, session_factory, stored_bytes
):
    """Ключ, которого система не знает, не отдаём (fail-closed)."""
    await _client(session_factory)
    await _login(api_client)

    r = await api_client.get(
        "/api/v1/files/photo", params={"key": "photos-series/never-seen.webp"}
    )
    assert r.status_code == 404, r.text
    assert stored_bytes.requested == []


async def test_photo_endpoint_serves_registered_photo_key(
    api_client, session_factory, stored_bytes
):
    """Фото каталога (есть в реестре медиа) отдаётся клиенту."""
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        await media_service.register_key(s, SERIES_KEY, commit=True)

    r = await api_client.get("/api/v1/files/photo", params={"key": SERIES_KEY})
    assert r.status_code == 200, r.text
    assert r.content == b"webp-bytes"
    assert stored_bytes.requested == [SERIES_KEY]


async def test_photo_endpoint_serves_thumb_variant_of_known_key(
    api_client, session_factory, stored_bytes
):
    """Миниатюра известного фото — тоже известный ключ (конвенция §16 п.17).

    Реестр хранит base-ключ (``photos-series/a.webp``), а мобильный каталог
    по конвенции запрашивает ``photos-series/a_thumb.webp``. Если бы
    проверка известности смотрела только точный ключ, миниатюра считалась бы
    «чужой» — и картинка в каталоге не отдавалась бы вовсе.
    """
    await _client(session_factory)
    await _login(api_client)
    async with session_factory() as s:
        await media_service.register_key(s, SERIES_KEY, commit=True)

    thumb_key = media_service.thumb_key_for(SERIES_KEY)
    r = await api_client.get("/api/v1/files/photo", params={"key": thumb_key})
    assert r.status_code == 200, r.text
    assert r.content == b"webp-bytes"
    assert stored_bytes.requested == [thumb_key]


async def test_photo_endpoint_serves_banner_key(
    api_client, session_factory, stored_bytes
):
    """Картинка баннера живёт в своём реестре (таблица banners) — тоже отдаём."""
    await _client(session_factory)
    await _login(api_client)
    banner_key = f"banners/{uuid.uuid4()}.webp"
    async with session_factory() as s:
        s.add(
            Banner(
                title="Баннер",
                image_key=banner_key,
                position=BannerPosition.PROMO,
                is_active=True,
            )
        )
        await s.commit()

    r = await api_client.get("/api/v1/files/photo", params={"key": banner_key})
    assert r.status_code == 200, r.text
    assert r.content == b"webp-bytes"


async def test_photo_endpoint_still_rejects_traversal(
    api_client, session_factory, stored_bytes
):
    """Path traversal отсекается до обращения к бакету."""
    await _client(session_factory)
    await _login(api_client)

    r = await api_client.get(
        "/api/v1/files/photo", params={"key": "photos-series/../../etc/passwd"}
    )
    assert r.status_code == 400, r.text
    assert stored_bytes.requested == []


# =========================================================
# Самовосстановление реестра медиа
# =========================================================
async def test_v2_catalog_registers_missing_media_key(
    api_client, session_factory, stored_bytes
):
    """Ключ фото, попавший в каталог не через реестр, регистрируется каталогом.

    Иначе /api/v2/media/{id} отвечал бы 404, и карточка показывала заглушку
    вместо фото.
    """
    await _client(session_factory)
    await _login(api_client)
    brand = await create_brand(session_factory, name="Keaz")
    series = await create_series(
        session_factory, brand=brand, name="Serie A", photo_key=SERIES_KEY
    )
    await create_product(
        session_factory, sku="SKU-1", name="Щит 1", brand=brand, series=series
    )

    async with session_factory() as s:
        assert await media_service.is_registered(s, SERIES_KEY) is False

    r = await api_client.get("/api/v2/catalog/products", params={"limit": 10})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    thumb = data[0]["thumbnail"]
    assert thumb is not None
    assert thumb["url"].startswith("/api/v2/media/")

    async with session_factory() as s:
        assert await media_service.is_registered(s, SERIES_KEY) is True

    # И по выданному id фото теперь действительно отдаётся.
    media_id = thumb["url"].removeprefix("/api/v2/media/").split("?")[0]
    img = await api_client.get(f"/api/v2/media/{media_id}", params={"size": "thumb"})
    assert img.status_code == 200, img.text
    assert img.content == b"webp-bytes"


async def test_v2_gallery_registers_missing_media_key(
    api_client, session_factory, stored_bytes
):
    """Фото галереи товара тоже регистрируются по запросу карточки."""
    await _client(session_factory)
    await _login(api_client)
    brand = await create_brand(session_factory, name="Keaz")
    product = await create_product(
        session_factory, sku="SKU-2", name="Щит 2", brand=brand
    )
    async with session_factory() as s:
        s.add(ProductPhoto(product_id=product.id, photo_key=PRODUCT_KEY, sort_order=0))
        await s.commit()

    r = await api_client.get(
        f"/api/v2/catalog/products/by-sku/{product.sku}"
    )
    assert r.status_code == 200, r.text
    media = r.json()["data"]["media"]
    assert len(media) == 1
    assert media[0]["url"].startswith("/api/v2/media/")

    async with session_factory() as s:
        assert await media_service.is_registered(s, PRODUCT_KEY) is True


# =========================================================
# «Сырые» ключи из CSV наружу не отдаются
# =========================================================
async def test_v1_catalog_drops_raw_photo_key(api_client, session_factory):
    """Сырое имя файла из CSV — не S3-ключ: в DTO его быть не должно."""
    await _client(session_factory)
    await _login(api_client)
    brand = await create_brand(session_factory, name="Keaz")
    series = await create_series(
        session_factory, brand=brand, name="Serie A", photo_key="serie_a.jpg"
    )
    await create_product(
        session_factory, sku="SKU-3", name="Щит 3", brand=brand, series=series
    )

    r = await api_client.get("/api/v1/catalog/products", params={"per_page": 10})
    assert r.status_code == 200, r.text
    card = r.json()["data"][0]
    assert card["photo_key"] is None
    assert card["series"]["photo_key"] is None


async def test_v2_catalog_thumbnail_none_for_raw_photo_key(
    api_client, session_factory
):
    """В v2 у товара без нормального фото thumbnail = None, а не вечная 404."""
    await _client(session_factory)
    await _login(api_client)
    brand = await create_brand(session_factory, name="Keaz")
    series = await create_series(
        session_factory, brand=brand, name="Serie A", photo_key="serie_a.jpg"
    )
    await create_product(
        session_factory, sku="SKU-4", name="Щит 4", brand=brand, series=series
    )

    r = await api_client.get("/api/v2/catalog/products", params={"limit": 10})
    assert r.status_code == 200, r.text
    assert r.json()["data"][0]["thumbnail"] is None


# =========================================================
# Фактические размеры вместо конвенции загрузчика
# =========================================================
async def test_register_key_stores_actual_dimensions(session_factory, stored_objects):
    """В реестр пишется размер РЕАЛЬНОГО кадра, а не бокса 1200×1200.

    Загрузчик вписывает фото в бокс без кропа и без увеличения, поэтому
    кадр 800×600 остаётся 800×600. Клиент рисует картинку по размерам из
    реестра — отсюда нужен настоящий размер, а не конвенция.
    """
    stored_objects[SERIES_KEY] = _png_bytes((800, 600))

    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)

    assert (asset.width, asset.height) == (800, 600)


async def test_register_key_falls_back_to_convention(
    session_factory, stored_objects
):
    """Объекта нет в бакете — размеры откатываются к конвенции 1200×1200."""
    async with session_factory() as s:
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)

    assert (asset.width, asset.height) == (1200, 1200)


async def test_register_key_thumb_stores_actual_dimensions(
    session_factory, stored_objects
):
    """Thumb-ключ: конвенция 400×400, фактический кадр — по объекту."""
    thumb_key = "photos-series/serie-a_thumb.webp"
    stored_objects[thumb_key] = _png_bytes((400, 300))

    async with session_factory() as s:
        asset = await media_service.register_key(s, thumb_key, commit=True)

    assert (asset.width, asset.height) == (400, 300)


async def test_register_key_uses_given_dimensions_without_reading_s3(
    session_factory, stored_objects
):
    """Загрузчик знает размер после ресайза — лишнего чтения из S3 не нужно.

    Если бы размер мерялся по объекту, кадр в реестре разошёлся бы с тем,
    что реально залил загрузчик (в т.ч. при несовпадении конвенции).
    """
    async with session_factory() as s:
        asset = await media_service.register_key(
            s, SERIES_KEY, dimensions=(1024, 768), commit=True
        )

    assert (asset.width, asset.height) == (1024, 768)
    assert stored_objects == {}


async def test_ensure_registered_stores_actual_dimensions(
    session_factory, stored_objects
):
    """Дописывание ключа в реестр (самовосстановление каталога) — тоже факт."""
    stored_objects[SERIES_KEY] = _png_bytes((640, 480))

    async with session_factory() as s:
        added = await media_service.ensure_registered(s, [SERIES_KEY])

    assert added == 1
    async with session_factory() as s:
        asset = await media_service.get_asset(s, media_service.media_id_for_key(SERIES_KEY))
    assert asset is not None
    assert (asset.width, asset.height) == (640, 480)


async def test_probe_dimensions_returns_none_for_unreadable_object(
    session_factory, stored_objects
):
    """Неизвестный объект/не-изображение — замер молча отдаёт None."""
    stored_objects[SERIES_KEY] = b"not-an-image-at-all"

    async with session_factory() as s:
        assert await media_service.probe_dimensions(SERIES_KEY) is None
        # Регистрация при этом не падает — размеры берутся из конвенции.
        asset = await media_service.register_key(s, SERIES_KEY, commit=True)

    assert (asset.width, asset.height) == (1200, 1200)


# =========================================================
# Конвенция thumb-ключа
# =========================================================
def test_thumb_key_convention():
    """Один конвенция на всех: заменяется только последнее .webp."""
    assert (
        media_service.thumb_key_for("photos-series/a.webp")
        == "photos-series/a_thumb.webp"
    )
    # Уже миниатюра — не удваиваем суффикс (раньше было a_thumb_thumb.webp).
    assert (
        media_service.thumb_key_for("photos-series/a_thumb.webp")
        == "photos-series/a_thumb.webp"
    )
    # Составной ключ: меняется только расширение, а не все вхождения.
    assert (
        media_service.thumb_key_for("photos-series/a.webp.b.webp")
        == "photos-series/a.webp.b_thumb.webp"
    )
    # Не webp — варианта нет, ключ не меняется.
    assert media_service.thumb_key_for("photos-series/a.jpg") == "photos-series/a.jpg"
