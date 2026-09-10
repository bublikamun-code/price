"""Тесты публичной SEO-витрины (/api/v1/public). См. §16 п.29.

Без аутентификации: бренды, деталка бренда с сериями, номенклатура серии
(видимость как в каталоге: deleted_at IS NULL, не ARCHIVED), /photo с
whitelist-валидацией ключа (анти arbitrary-file-read).
"""
from datetime import datetime, timezone

import pytest

from sqlalchemy import select

from app.models.catalog import Product
from app.models.enums import StockStatus
from app.models.system import Notification
from app.services.storage import StorageError
from tests.conftest import create_brand, create_product, create_series


async def _mark_deleted(sf, product: Product) -> None:
    async with sf() as s:
        db_product = await s.get(Product, product.id)
        db_product.deleted_at = datetime.now(timezone.utc)
        await s.commit()


@pytest.fixture
def _storage_stub(monkeypatch):
    """Мок storage.get_bytes: пишет вызовы, по умолчанию возвращает байты webp."""
    calls: list[tuple[str, str]] = []

    def _get_bytes(bucket: str, key: str) -> bytes:
        calls.append((bucket, key))
        return b"RIFF\x00\x00fake-webp"

    monkeypatch.setattr("app.services.storage.get_bytes", _get_bytes)
    return calls


# ------------------------------------------------------------------ brands
async def test_list_brands_no_auth(api_client, session_factory):
    sf = session_factory
    await create_brand(sf, name="acme", slug="acme")
    await create_brand(sf, name="beta", slug="beta")
    await create_brand(sf, name="gamma", slug="gamma")

    r = await api_client.get("/api/v1/public/brands")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["slug"] for b in body["data"]] == ["acme", "beta", "gamma"]
    item = body["data"][0]
    # Витрина лендинга (§16 п.29): фото + счётчики серий/товаров
    assert set(item) == {"id", "name", "slug", "photo", "series_count", "products_count"}
    assert item["name"] == "acme"


async def test_brand_detail_with_series(api_client, session_factory):
    sf = session_factory
    brand = await create_brand(sf, name="acme", slug="acme")
    await create_series(sf, brand=brand, name="alpha", photo_key="photos-series/alpha.webp")
    await create_series(sf, brand=brand, name="zeta")  # без фото
    other = await create_brand(sf, name="beta", slug="beta")
    await create_series(sf, brand=other, name="alien")

    r = await api_client.get("/api/v1/public/brands/acme")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["slug"] == "acme"
    assert data["name"] == "acme"
    slugs = [s["slug"] for s in data["series"]]
    assert len(slugs) == 2 and len(set(slugs)) == 2  # slug серии — непрозрачный токен
    by_name = {s["name"]: s for s in data["series"]}
    assert by_name["alpha"]["photo_thumb"] == "photos-series/alpha_thumb.webp"
    assert by_name["zeta"]["photo_thumb"] is None

    # Чужие серии не протекают
    assert "alien" not in {s["name"] for s in data["series"]}

    # Неизвестный бренд → 404 (фронт по 404 показывает свою страницу)
    assert (await api_client.get("/api/v1/public/brands/nope")).status_code == 404


# ------------------------------------------------------- series products
async def test_series_products_visibility_and_pagination(api_client, session_factory):
    sf = session_factory
    brand = await create_brand(sf, name="acme", slug="acme")
    series = await create_series(sf, brand=brand, name="alpha")
    other_series = await create_series(sf, brand=brand, name="zeta")

    await create_product(sf, sku="A2", name="beta-lamp", brand=brand, series=series)
    await create_product(sf, sku="A1", name="alpha-lamp", brand=brand, series=series)
    await create_product(sf, sku="A3", name="gamma-lamp", brand=brand, series=series)
    # Не видимые: ARCHIVED и soft-delete (правила каталога §7)
    await create_product(
        sf, sku="A4", name="archived-lamp", brand=brand, series=series,
        stock=StockStatus.ARCHIVED,
    )
    deleted = await create_product(sf, sku="A5", name="deleted-lamp", brand=brand, series=series)
    await _mark_deleted(sf, deleted)
    # Чужая серия не подмешивается
    await create_product(sf, sku="Z1", name="alien-lamp", brand=brand, series=other_series)

    url = f"/api/v1/public/series/{series.id}/products"
    r = await api_client.get(url, params={"page": 1, "per_page": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["sku"] for p in body["data"]] == ["A1", "A2"]  # сортировка по имени
    assert body["meta"] == {"page": 1, "per_page": 2, "total": 3}

    r = await api_client.get(url, params={"page": 2, "per_page": 2})
    body = r.json()
    assert [p["sku"] for p in body["data"]] == ["A3"]
    assert body["meta"]["total"] == 3

    # Поля без цен/остатков (публичная витрина)
    r = await api_client.get(url, params={"per_page": 200})
    assert r.status_code == 200
    # photo — личное фото товара (ключ photos-product/…), добавлено 2026-09-08
    assert all(set(p) == {"sku", "name", "photo"} for p in r.json()["data"])
    assert len(r.json()["data"]) == 3

    # Кап per_page как в каталоге
    assert (await api_client.get(url, params={"per_page": 201})).status_code == 422
    # Неизвестная серия / не-UUID slug → 404
    assert (await api_client.get("/api/v1/public/series/nope/products")).status_code == 404


# ------------------------------------------------------------------ photo
async def test_photo_streams_whitelisted_key(api_client, _storage_stub):
    r = await api_client.get("/api/v1/public/photo", params={"key": "photos-series/alpha.webp"})
    assert r.status_code == 200, r.text
    assert r.content == b"RIFF\x00\x00fake-webp"
    assert r.headers["content-type"] == "image/webp"
    assert _storage_stub[0][1] == "photos-series/alpha.webp"

    # Thumb-вариант тоже разрешён (фронт запрашивает именно его)
    r = await api_client.get(
        "/api/v1/public/photo", params={"key": "photos-series/alpha_thumb.webp"}
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "key",
    [
        "",  # пустой
        "photos-series/../secret.webp",  # path traversal
        "s3://bucket/photos-series/x.webp",  # схема
        "photos-product/11111111-1111-1111-1111-111111111111/abc.webp",  # чужой префикс
        "files/docs/contract.pdf",  # произвольный префикс
        "photos-series/x.pdf",  # не изображение
        "photos-series/x",  # без расширения
    ],
)
async def test_photo_rejects_keys_outside_whitelist(api_client, _storage_stub, key):
    r = await api_client.get("/api/v1/public/photo", params={"key": key})
    assert r.status_code == 400, r.text
    assert _storage_stub == []  # до S3 дело не дошло


async def test_photo_missing_object_404(api_client, monkeypatch):
    def _raise_sync(bucket, key):  # noqa: ANN001
        raise StorageError(f"Не удалось прочитать объект {bucket}/{key}")

    monkeypatch.setattr("app.services.storage.get_bytes", _raise_sync)
    r = await api_client.get(
        "/api/v1/public/photo", params={"key": "photos-series/ghost.webp"}
    )
    assert r.status_code == 404, r.text


async def test_lead_creates_manager_notification(api_client, session_factory):
    """Лид-форма лендинга: 201 + уведомление всем менеджерам (user_id=None)."""
    r = await api_client.post(
        "/api/v1/public/lead",
        json={
            "company": "ООО «Тест-строй»",
            "contact_name": "Иван Тестов",
            "phone": "+375291112233",
            "email": "test@example.com",
            "comment": "Нужны цены на OptiBox Pro",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"ok": True}

    async with session_factory() as db:
        notif = (
            await db.execute(
                select(Notification).where(Notification.type == "LEAD_CREATED")
            )
        ).scalars().first()
    assert notif is not None
    assert notif.user_id is None  # рассылка всем менеджерам (§20)
    assert "ООО «Тест-строй»" in (notif.body or "")
    assert "Иван Тестов" in (notif.body or "")


async def test_lead_honeypot_silent_ok(api_client, session_factory):
    """Заполненный honeypot — ответ успешный, но лид не создаётся."""
    r = await api_client.post(
        "/api/v1/public/lead",
        json={
            "company": "Бот Инк",
            "contact_name": "Bot Botov",
            "phone": "+375290000000",
            "website": "http://spam.example",
        },
    )
    assert r.status_code == 201, r.text

    async with session_factory() as db:
        notif = (
            await db.execute(
                select(Notification).where(Notification.type == "LEAD_CREATED")
            )
        ).scalars().first()
    assert notif is None


async def test_lead_validation_422(api_client):
    r = await api_client.post(
        "/api/v1/public/lead",
        json={"company": "ООО", "contact_name": "", "phone": "123"},
    )
    assert r.status_code == 422, r.text
