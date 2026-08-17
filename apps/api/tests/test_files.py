"""Тесты файлового архива (§16 п.18): /files, /manager/files.

Слои:
  1. GET /files — CLIENT видит только PUBLIC/AUTHED (MANAGER_ONLY нет),
     MANAGER — все; фильтры type/brand_id; неавторизованный → 401.
  2. GET /files/{id}/download — 200 {"data": {url, expires_in: 300}},
     недоступная visibility / несуществующий → 404.
  3. POST /manager/files — 201 + поля и s3-ключ; 415 (расширение,
     content-type, magic-bytes); 422 (PHOTO_ZIP); 413 (лимит);
     клиент → 403; несуществующий brand_id → 404.
  4. GET /manager/files — все записи + фильтр visibility.
  5. DELETE /manager/files/{id} — 204 + удаление S3-объекта; повторно 404.

S3 мокается monkeypatch'ем функций модуля app.services.storage
(upload_fileobj / presigned_get / delete_object). Лимитер отключён
в api_client (conftest).
"""
import io
import re
import uuid

import pytest

from app.models.enums import FileAssetType, FileVisibility, UserRole
from app.models.file import FileAsset
from tests.conftest import create_brand, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"

_PDF_BODY = b"%PDF-1.4 fake pdf body"


# ---------- helpers ----------

async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _create_asset(sf, **kwargs) -> FileAsset:
    """Создать запись файла напрямую в БД (S3 не трогаем)."""
    defaults: dict = dict(
        type=FileAssetType.BRAND_PDF,
        s3_key="brand_pdf/test.pdf",
        filename_display="test.pdf",
        content_type="application/pdf",
        size_bytes=100,
        visibility=FileVisibility.PUBLIC,
    )
    defaults.update(kwargs)
    async with sf() as s:
        asset = FileAsset(**defaults)
        s.add(asset)
        await s.commit()
        await s.refresh(asset)
        return asset


# ---------- S3-моки ----------

@pytest.fixture
def uploads(monkeypatch):
    """Перехват upload_fileobj: складывает (bucket, key, kwargs) в список."""
    captured: list[dict] = []

    def _upload(bucket, key, fileobj, **kwargs):
        captured.append({"bucket": bucket, "key": key, "kwargs": kwargs})

    monkeypatch.setattr("app.services.storage.upload_fileobj", _upload)
    return captured


@pytest.fixture
def presigned(monkeypatch):
    monkeypatch.setattr(
        "app.services.storage.presigned_get",
        lambda bucket, key, **kw: f"http://minio.local/{key}",
    )


@pytest.fixture
def deleted(monkeypatch):
    """Перехват delete_object: фиксирует (bucket, key)."""
    calls: list[tuple] = []

    def _delete(bucket, key):
        calls.append((bucket, key))

    monkeypatch.setattr("app.services.storage.delete_object", _delete)
    return calls


# ===========================================================================
# 1. GET /files
# ===========================================================================
@pytest.mark.asyncio
class TestListFiles:
    async def test_client_sees_public_authed_only(
        self, api_client, session_factory
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _create_asset(
            session_factory,
            filename_display="public.pdf",
            visibility=FileVisibility.PUBLIC,
        )
        await _create_asset(
            session_factory,
            filename_display="authed.pdf",
            visibility=FileVisibility.AUTHED,
        )
        await _create_asset(
            session_factory,
            filename_display="secret.pdf",
            visibility=FileVisibility.MANAGER_ONLY,
        )
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get("/api/v1/files")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [f["filename"] for f in body["data"]] == ["authed.pdf", "public.pdf"]
        assert {f["visibility"] for f in body["data"]} == {"PUBLIC", "AUTHED"}
        assert body["meta"] == {"page": 1, "per_page": 20, "total": 2}

    async def test_manager_sees_all(self, api_client, session_factory):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        for vis in (FileVisibility.PUBLIC, FileVisibility.AUTHED, FileVisibility.MANAGER_ONLY):
            await _create_asset(session_factory, visibility=vis)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.get("/api/v1/files")
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["total"] == 3

    async def test_filter_type_and_brand(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="KEAZ")
        await _create_asset(
            session_factory, type=FileAssetType.BRAND_PDF, brand_id=brand.id
        )
        await _create_asset(
            session_factory,
            type=FileAssetType.CUSTOM_CSV,
            s3_key="custom_csv/prices.csv",
            filename_display="prices.csv",
            visibility=FileVisibility.PUBLIC,
        )
        await _create_asset(session_factory)  # другой тип, без бренда
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(
            "/api/v1/files", params={"type": "CUSTOM_CSV"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["filename"] == "prices.csv"
        assert body["data"][0]["type"] == "CUSTOM_CSV"

        r = await api_client.get(
            "/api/v1/files", params={"brand_id": str(brand.id)}
        )
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["brand_id"] == str(brand.id)
        assert body["data"][0]["brand_name"] == "KEAZ"

    async def test_unauthorized_401(self, api_client):
        r = await api_client.get("/api/v1/files")
        assert r.status_code == 401, r.text


# ===========================================================================
# 2. GET /files/{id}/download
# ===========================================================================
@pytest.mark.asyncio
class TestDownload:
    async def test_200_presigned_url(self, api_client, session_factory, presigned):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        asset = await _create_asset(session_factory, visibility=FileVisibility.AUTHED)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(f"/api/v1/files/{asset.id}/download")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "data": {"url": f"http://minio.local/{asset.s3_key}", "expires_in": 300}
        }

    async def test_404_for_hidden_visibility(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        asset = await _create_asset(
            session_factory, visibility=FileVisibility.MANAGER_ONLY
        )
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(f"/api/v1/files/{asset.id}/download")
        assert r.status_code == 404, r.text

    async def test_manager_downloads_manager_only(
        self, api_client, session_factory, presigned
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        asset = await _create_asset(
            session_factory, visibility=FileVisibility.MANAGER_ONLY
        )
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.get(f"/api/v1/files/{asset.id}/download")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["url"].endswith(asset.s3_key)

    async def test_404_missing(self, api_client, session_factory, presigned):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(f"/api/v1/files/{uuid.uuid4()}/download")
        assert r.status_code == 404, r.text


# ===========================================================================
# 3. POST /manager/files
# ===========================================================================
@pytest.mark.asyncio
class TestUploadEndpoint:
    async def test_upload_201_with_fields(
        self, api_client, session_factory, uploads
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="KEAZ")
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("catalog.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={
                "type": "BRAND_PDF",
                "visibility": "PUBLIC",
                "brand_id": str(brand.id),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["filename"] == "catalog.pdf"
        assert body["type"] == "BRAND_PDF"
        assert body["visibility"] == "PUBLIC"
        assert body["brand_id"] == str(brand.id)
        assert body["brand_name"] == "KEAZ"
        assert body["size_bytes"] == len(_PDF_BODY)
        assert body["content_type"] == "application/pdf"

        # Стриминг в бакет pdf-catalogs под ключом brand_pdf/{uuid}.pdf
        assert len(uploads) == 1
        assert uploads[0]["bucket"] == "pdf-catalogs"
        assert re.fullmatch(r"brand_pdf/[0-9a-f-]{36}\.pdf", uploads[0]["key"])
        assert uploads[0]["kwargs"]["content_type"] == "application/pdf"

        # Запись в БД указывает на залитый ключ
        async with session_factory() as s:
            stored = await s.get(FileAsset, uuid.UUID(body["id"]))
            assert stored is not None
            assert stored.s3_key == uploads[0]["key"]
            assert stored.filename_display == "catalog.pdf"

    async def test_default_visibility_authed_and_csv(
        self, api_client, session_factory, uploads
    ):
        """Без visibility → AUTHED; CSV (без magic-проверки) проходит как OTHER."""
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        csv_body = b"sku,name\nA,Test\n"
        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("prices.csv", io.BytesIO(csv_body), "text/csv")},
            data={"type": "OTHER"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["visibility"] == "AUTHED"
        assert body["brand_id"] is None and body["brand_name"] is None
        assert uploads[0]["key"].startswith("other/") and uploads[0]["key"].endswith(".csv")

    async def test_wrong_extension_and_content_type_415(
        self, api_client, session_factory, uploads
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("notes.txt", io.BytesIO(b"just text"), "text/plain")},
            data={"type": "OTHER"},
        )
        assert r.status_code == 415, r.text

        # .pdf-имя, но Content-Type не pdf-шный
        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("x.pdf", io.BytesIO(_PDF_BODY), "text/csv")},
            data={"type": "BRAND_PDF"},
        )
        assert r.status_code == 415, r.text
        assert uploads == []  # ничего не заливалось

    async def test_bad_magic_bytes_415(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        # .pdf без сигнатуры %PDF
        r = await api_client.post(
            "/api/v1/manager/files",
            files={
                "file": ("fake.pdf", io.BytesIO(b"NOTPDF" + b"x" * 50), "application/pdf")
            },
            data={"type": "BRAND_PDF"},
        )
        assert r.status_code == 415, r.text

        # .zip без сигнатуры PK
        r = await api_client.post(
            "/api/v1/manager/files",
            files={
                "file": ("fake.zip", io.BytesIO(b"NOPE" + b"x" * 50), "application/zip")
            },
            data={"type": "OTHER"},
        )
        assert r.status_code == 415, r.text
        assert uploads == []

    async def test_photo_zip_type_422(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("photos.zip", io.BytesIO(b"PK" + b"x" * 10), "application/zip")},
            data={"type": "PHOTO_ZIP"},
        )
        assert r.status_code == 422, r.text
        assert uploads == []

    async def test_oversize_413(self, api_client, session_factory, uploads, monkeypatch):
        from app.core.config import settings

        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        monkeypatch.setattr(settings, "files_max_mb", 0)  # любой файл > 0 МБ

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("catalog.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={"type": "BRAND_PDF"},
        )
        assert r.status_code == 413, r.text
        assert uploads == []

    async def test_client_403(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("catalog.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={"type": "BRAND_PDF"},
        )
        assert r.status_code == 403, r.text
        assert uploads == []

    async def test_unknown_brand_404(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/files",
            files={"file": ("catalog.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={"type": "BRAND_PDF", "brand_id": str(uuid.uuid4())},
        )
        assert r.status_code == 404, r.text
        assert uploads == []


# ===========================================================================
# 4. GET /manager/files
# ===========================================================================
@pytest.mark.asyncio
class TestManagerList:
    async def test_returns_all_records_with_visibility_filter(
        self, api_client, session_factory
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _create_asset(session_factory, visibility=FileVisibility.PUBLIC)
        await _create_asset(session_factory, visibility=FileVisibility.AUTHED)
        await _create_asset(
            session_factory,
            s3_key="brand_pdf/secret.pdf",
            filename_display="secret.pdf",
            visibility=FileVisibility.MANAGER_ONLY,
        )
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.get("/api/v1/manager/files")
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["total"] == 3

        r = await api_client.get(
            "/api/v1/manager/files", params={"visibility": "MANAGER_ONLY"}
        )
        body = r.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["filename"] == "secret.pdf"
        assert body["data"][0]["visibility"] == "MANAGER_ONLY"

    async def test_client_403(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get("/api/v1/manager/files")
        assert r.status_code == 403, r.text


# ===========================================================================
# 5. DELETE /manager/files/{id}
# ===========================================================================
@pytest.mark.asyncio
class TestDeleteEndpoint:
    async def test_delete_204_and_s3_removed(
        self, api_client, session_factory, deleted
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        asset = await _create_asset(session_factory)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.delete(f"/api/v1/manager/files/{asset.id}")
        assert r.status_code == 204, r.text
        assert deleted == [("pdf-catalogs", asset.s3_key)]

        # Запись удалена из БД; повторное удаление → 404
        async with session_factory() as s:
            assert await s.get(FileAsset, asset.id) is None
        r = await api_client.delete(f"/api/v1/manager/files/{asset.id}")
        assert r.status_code == 404, r.text
        assert len(deleted) == 1  # повторно S3 не дёргали

    async def test_delete_missing_404(self, api_client, session_factory, deleted):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.delete(f"/api/v1/manager/files/{uuid.uuid4()}")
        assert r.status_code == 404, r.text
        assert deleted == []
