"""API v2 документы на товар: сертификаты/datasheets (§16 п.38).

Слои:
  1. POST /api/v2/manager/products|series/{id}/documents — 201 + запись;
     415 (расширение/content-type/magic-bytes, не-PDF), 422 (тип не
     CERTIFICATE|DATASHEET, мусорный valid_until, Idempotency-Key),
     404 (товар/серия), 403 (клиент), 413 (лимит).
  2. documents[] в v2 product detail — свои + документы серии (scope),
     просроченные помечаются is_expired, не скрываются; в списке — пусто.
  3. GET .../documents/{id}/download — 200 с байтами (не presigned — урок
     mixed-content 27.09), 401/404/502.
  4. DELETE /api/v2/manager/documents/{id} — 204 + удаление S3-объекта;
     повторно 404; файл архива (BRAND_PDF) сюда не попадает.

S3 мокается monkeypatch'ем функций модуля app.services.storage, как в
test_files.py / test_api_v2_media.py. Лимитер отключён в api_client.
"""
import io
import uuid
from datetime import date, timedelta

import pytest

from app.models.enums import FileAssetType, FileVisibility, UserRole
from app.models.file import FileAsset
from tests.conftest import create_brand, create_product, create_series, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "doc-manager@example.by"
CLIENT_EMAIL = "doc-client@example.by"

_PDF_BODY = b"%PDF-1.4 fake pdf body"


# ---------- helpers ----------

async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _create_document(sf, **kwargs) -> FileAsset:
    """Создать документ напрямую в БД (S3 не трогаем).

    Привязку (product_id/series_id) передаёт тест: FK в test-схеме реальный,
    несуществующий товар даст IntegrityError.
    """
    defaults: dict = dict(
        type=FileAssetType.CERTIFICATE,
        s3_key=f"certificate/{uuid.uuid4()}.pdf",
        filename_display="certificate.pdf",
        content_type="application/pdf",
        size_bytes=len(_PDF_BODY),
        valid_until=date.today() + timedelta(days=30),
        visibility=FileVisibility.AUTHED,
        product_id=None,
        series_id=None,
    )
    defaults.update(kwargs)
    async with sf() as s:
        asset = FileAsset(**defaults)
        s.add(asset)
        await s.commit()
        await s.refresh(asset)
        return asset


def _upload(files=None, data=None):
    return dict(
        files=files or {"file": ("cert.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
        data=data or {"type": "CERTIFICATE"},
    )


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
def stored_bytes(monkeypatch):
    requested: list[str] = []
    monkeypatch.setattr(
        "app.services.storage.get_bytes",
        lambda bucket, key, **kw: requested.append(key) or _PDF_BODY,
    )
    stored_bytes.requested = requested
    return stored_bytes


@pytest.fixture
def deleted(monkeypatch):
    calls: list[tuple] = []

    def _delete(bucket, key):
        calls.append((bucket, key))

    monkeypatch.setattr("app.services.storage.delete_object", _delete)
    return calls


# ===========================================================================
# 1. Загрузка (менеджер)
# ===========================================================================
@pytest.mark.asyncio
class TestUploadProductDocument:
    async def test_manager_uploads_pdf_201(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(
            session_factory, sku="DOC-1", name="Widget", brand=brand
        )
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/products/{product.id}/documents",
            files={"file": ("cert.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={"type": "CERTIFICATE", "valid_until": "2027-03-31"},
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["type"] == "CERTIFICATE"
        assert body["fileName"] == "cert.pdf"
        assert body["scope"] == "product"
        assert body["validUntil"] == "2027-03-31"
        assert body["isExpired"] is False

        # PDF стримится в бакет pdf-catalogs под ключом certificate/{uuid}.pdf
        assert len(uploads) == 1
        assert uploads[0]["bucket"] == "pdf-catalogs"
        assert uploads[0]["key"].startswith("certificate/")
        assert uploads[0]["key"].endswith(".pdf")

        async with session_factory() as s:
            stored = await s.get(FileAsset, uuid.UUID(body["id"]))
            assert stored is not None
            assert stored.s3_key == uploads[0]["key"]
            assert stored.product_id == product.id
            assert stored.series_id is None
            assert stored.valid_until.isoformat() == "2027-03-31"
            assert stored.visibility == FileVisibility.AUTHED

    async def test_manager_uploads_series_document(
        self, api_client, session_factory, uploads
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        series = await create_series(session_factory, brand=brand, name="Serie Doc")
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/series/{series.id}/documents",
            files={"file": ("ds.pdf", io.BytesIO(_PDF_BODY), "application/pdf")},
            data={"type": "DATASHEET"},
        )
        assert r.status_code == 201, r.text
        body = r.json()["data"]
        assert body["scope"] == "series"
        assert body["type"] == "DATASHEET"
        assert body["validUntil"] is None
        assert uploads[0]["key"].startswith("datasheet/")

        async with session_factory() as s:
            stored = await s.get(FileAsset, uuid.UUID(body["id"]))
            assert stored.series_id == series.id
            assert stored.product_id is None

    async def test_non_pdf_rejected_415(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-2", name="W", brand=brand)
        await _login(api_client, MANAGER_EMAIL)
        url = f"/api/v2/manager/products/{product.id}/documents"

        # Не то расширение
        r = await api_client.post(url, **_upload(
            files={"file": ("scan.jpg", io.BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg")},
        ))
        assert r.status_code == 415, r.text
        # PDF-имя, но не PDF-контент (magic-bytes)
        r = await api_client.post(url, **_upload(
            files={"file": ("fake.pdf", io.BytesIO(b"NOTPDF" + b"x" * 50), "application/pdf")},
        ))
        assert r.status_code == 415, r.text
        # PDF-контент, но не PDF-контент-тип
        r = await api_client.post(url, **_upload(
            files={"file": ("cert.pdf", io.BytesIO(_PDF_BODY), "text/plain")},
        ))
        assert r.status_code == 415, r.text
        assert uploads == []  # в S3 ничего не уходит

    async def test_wrong_type_422(self, api_client, session_factory, uploads):
        """Архивный тип без привязки в документы товара не проходит."""
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-3", name="W", brand=brand)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/products/{product.id}/documents", **_upload(
                data={"type": "BRAND_PDF"},
            )
        )
        assert r.status_code == 422, r.text
        assert uploads == []

    async def test_bad_valid_until_422_but_past_allowed(
        self, api_client, session_factory, uploads
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-4", name="W", brand=brand)
        await _login(api_client, MANAGER_EMAIL)
        url = f"/api/v2/manager/products/{product.id}/documents"

        r = await api_client.post(url, **_upload(data={"type": "CERTIFICATE", "valid_until": "31.03.2027"}))
        assert r.status_code == 422, r.text
        assert uploads == []

        r = await api_client.post(url, **_upload(data={"type": "CERTIFICATE", "valid_until": "1199-01-01"}))
        assert r.status_code == 422, r.text

        # Просроченный сертификат загрузить можно: клиенту он пометится.
        r = await api_client.post(url, **_upload(data={"type": "CERTIFICATE", "valid_until": "2020-01-01"}))
        assert r.status_code == 201, r.text
        assert r.json()["data"]["validUntil"] == "2020-01-01"
        assert r.json()["data"]["isExpired"] is True

    async def test_unknown_product_and_series_404(
        self, api_client, session_factory, uploads
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/products/{uuid.uuid4()}/documents", **_upload()
        )
        assert r.status_code == 404, r.text
        assert r.json()["code"] == "RESOURCE_NOT_FOUND"

        r = await api_client.post(
            f"/api/v2/manager/series/{uuid.uuid4()}/documents", **_upload()
        )
        assert r.status_code == 404, r.text
        assert uploads == []

    async def test_client_403(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-5", name="W", brand=brand)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/products/{product.id}/documents", **_upload()
        )
        assert r.status_code == 403, r.text
        r = await api_client.post(
            f"/api/v2/manager/series/{uuid.uuid4()}/documents", **_upload()
        )
        assert r.status_code == 403, r.text
        assert uploads == []

    async def test_oversize_413(self, api_client, session_factory, uploads, monkeypatch):
        from app.core.config import settings

        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-6", name="W", brand=brand)
        await _login(api_client, MANAGER_EMAIL)
        monkeypatch.setattr(settings, "files_max_mb", 0)

        r = await api_client.post(
            f"/api/v2/manager/products/{product.id}/documents", **_upload()
        )
        assert r.status_code == 413, r.text
        assert uploads == []

    async def test_bad_idempotency_key_422(self, api_client, session_factory, uploads):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-7", name="W", brand=brand)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            f"/api/v2/manager/products/{product.id}/documents",
            headers={"Idempotency-Key": "x" * 256},  # длиннее 255 → 422
            **_upload(),
        )
        assert r.status_code == 422, r.text
        assert uploads == []


# ===========================================================================
# 2. documents[] в product detail
# ===========================================================================
@pytest.mark.asyncio
class TestProductDetailDocuments:
    async def test_detail_lists_product_and_series_documents(
        self, api_client, session_factory
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        series = await create_series(session_factory, brand=brand, name="Serie Doc")
        product = await create_product(
            session_factory, sku="DOC-10", name="Widget", brand=brand, series=series
        )

        own = await _create_document(
            session_factory,
            product_id=product.id,
            series_id=None,
            valid_until=date.today() - timedelta(days=1),  # просрочен
            filename_display="expired-cert.pdf",
        )
        series_doc = await _create_document(
            session_factory,
            product_id=None,
            series_id=series.id,
            type=FileAssetType.DATASHEET,
            s3_key=f"datasheet/{uuid.uuid4()}.pdf",
            filename_display="series-datasheet.pdf",
            valid_until=None,
        )
        # Чужой документ другого товара не должен попасть в карточку.
        other_product = await create_product(
            session_factory, sku="DOC-11", name="Other", brand=brand
        )
        await _create_document(session_factory, product_id=other_product.id)

        await _login(api_client, CLIENT_EMAIL)

        by_id = await api_client.get(f"/api/v2/catalog/products/{product.id}")
        by_sku = await api_client.get("/api/v2/catalog/products/by-sku/DOC-10")
        for r in (by_id, by_sku):
            assert r.status_code == 200, r.text
            documents = r.json()["data"]["documents"]
            # Порядок не фиксируем контрактом; важен состав.
            assert {d["id"] for d in documents} == {str(series_doc.id), str(own.id)}
            by_scope = {d["scope"]: d for d in documents}
            assert by_scope["series"]["type"] == "DATASHEET"
            # Просроченный помечен, но присутствует.
            own_view = [d for d in documents if d["scope"] == "product"][0]
            assert own_view["isExpired"] is True
            assert own_view["fileName"] == "expired-cert.pdf"
            series_view = by_scope["series"]
            assert series_view["validUntil"] is None
            assert series_view["isExpired"] is False
            # S3-ключ наружу не утекает.
            assert own.s3_key not in r.text

    async def test_list_has_empty_documents(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-12", name="W", brand=brand)
        await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get("/api/v2/catalog/products")
        assert r.status_code == 200
        assert r.json()["data"][0]["documents"] == []

    async def test_non_document_types_are_not_listed(
        self, api_client, session_factory
    ):
        """BRAND_PDF с product_id (теоретически) не попадает в documents[]."""
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-13", name="W", brand=brand)
        await _create_document(
            session_factory,
            product_id=product.id,
            type=FileAssetType.BRAND_PDF,
            s3_key=f"brand_pdf/{uuid.uuid4()}.pdf",
        )
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(f"/api/v2/catalog/products/{product.id}")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["documents"] == []


# ===========================================================================
# 3. Скачивание байтами
# ===========================================================================
@pytest.mark.asyncio
class TestDownload:
    async def test_bytes_200_no_redirect(
        self, api_client, session_factory, stored_bytes
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-20", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 200, r.text
        # Байты отдаёт сам API: редирект на presigned резался бы браузером
        # как mixed content (§16 п.37).
        assert "location" not in r.headers
        assert r.content == _PDF_BODY
        assert r.headers["content-type"].startswith("application/pdf")
        assert stored_bytes.requested == [doc.s3_key]
        assert doc.s3_key not in str(dict(r.headers))

    async def test_series_document_downloads_via_product(
        self, api_client, session_factory, stored_bytes
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        series = await create_series(session_factory, brand=brand, name="Serie DL")
        product = await create_product(
            session_factory, sku="DOC-21", name="W", brand=brand, series=series
        )
        doc = await _create_document(
            session_factory,
            product_id=None,
            series_id=series.id,
            type=FileAssetType.DATASHEET,
            s3_key=f"datasheet/{uuid.uuid4()}.pdf",
        )
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 200, r.text
        assert r.content == _PDF_BODY

    async def test_requires_authentication(self, api_client, session_factory, stored_bytes):
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-22", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)

        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 401

    async def test_foreign_or_missing_document_404(
        self, api_client, session_factory, stored_bytes
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-23", name="W", brand=brand)
        other = await create_product(session_factory, sku="DOC-24", name="O", brand=brand)
        doc = await _create_document(session_factory, product_id=other.id)
        await _login(api_client, CLIENT_EMAIL)

        # Чужой документ не выдаётся через карточку другого товара…
        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 404, r.text
        assert r.headers["content-type"].startswith("application/problem+json")
        # …и неизвестный id тоже 404.
        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{uuid.uuid4()}/download"
        )
        assert r.status_code == 404, r.text
        assert stored_bytes.requested == []

    async def test_archived_product_hides_documents_404(
        self, api_client, session_factory, stored_bytes
    ):
        """Товар вне видимости (ARCHIVED) → карточка и документ недоступны."""
        from app.models.enums import StockStatus

        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(
            session_factory, sku="DOC-25", name="W", brand=brand, stock=StockStatus.ARCHIVED
        )
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 404, r.text

    async def test_missing_object_404(self, api_client, session_factory, monkeypatch):
        from app.services import storage

        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-26", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        def _missing(bucket, key, **kw):
            raise storage.ObjectNotFound(f"нет {key}")

        monkeypatch.setattr("app.services.storage.get_bytes", _missing)
        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 404, r.text
        assert r.json()["code"] == "RESOURCE_NOT_FOUND"

    async def test_storage_failure_502(self, api_client, session_factory, monkeypatch):
        from app.services import storage

        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-27", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        def _boom(bucket, key, **kw):
            raise storage.StorageError("minio недоступен")

        monkeypatch.setattr("app.services.storage.get_bytes", _boom)
        r = await api_client.get(
            f"/api/v2/catalog/products/{product.id}/documents/{doc.id}/download"
        )
        assert r.status_code == 502, r.text
        assert r.json()["code"] == "STORAGE_UNAVAILABLE"


# ===========================================================================
# 4. Удаление (менеджер)
# ===========================================================================
@pytest.mark.asyncio
class TestDelete:
    async def test_manager_deletes_204_and_s3_removed(
        self, api_client, session_factory, deleted
    ):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-30", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.delete(f"/api/v2/manager/documents/{doc.id}")
        assert r.status_code == 204, r.text
        assert deleted == [("pdf-catalogs", doc.s3_key)]

        async with session_factory() as s:
            assert await s.get(FileAsset, doc.id) is None
        r = await api_client.delete(f"/api/v2/manager/documents/{doc.id}")
        assert r.status_code == 404, r.text
        assert len(deleted) == 1  # повторно S3 не дёргали

    async def test_archive_file_is_not_a_document_404(
        self, api_client, session_factory, deleted
    ):
        """BRAND_PDF-файл архива удаляется через v1 /manager/files, не сюда."""
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        archive_file = await _create_document(
            session_factory,
            type=FileAssetType.BRAND_PDF,
            s3_key=f"brand_pdf/{uuid.uuid4()}.pdf",
            product_id=None,
        )
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.delete(f"/api/v2/manager/documents/{archive_file.id}")
        assert r.status_code == 404, r.text
        assert deleted == []

    async def test_client_403(self, api_client, session_factory, deleted):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-31", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.delete(f"/api/v2/manager/documents/{doc.id}")
        assert r.status_code == 403, r.text
        assert deleted == []

    async def test_unknown_404(self, api_client, session_factory, deleted):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.delete(f"/api/v2/manager/documents/{uuid.uuid4()}")
        assert r.status_code == 404, r.text
        assert deleted == []

    async def test_storage_failure_keeps_record_502(
        self, api_client, session_factory, monkeypatch
    ):
        from app.services import storage

        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        brand = await create_brand(session_factory, name="Doc Brand")
        product = await create_product(session_factory, sku="DOC-32", name="W", brand=brand)
        doc = await _create_document(session_factory, product_id=product.id)
        await _login(api_client, MANAGER_EMAIL)

        def _boom(bucket, key):
            raise storage.StorageError("minio недоступен")

        monkeypatch.setattr("app.services.storage.delete_object", _boom)
        r = await api_client.delete(f"/api/v2/manager/documents/{doc.id}")
        assert r.status_code == 502, r.text
        # Запись не тронута: нет документа без объекта в хранилище (§16 п.18).
        async with session_factory() as s:
            assert await s.get(FileAsset, doc.id) is not None
