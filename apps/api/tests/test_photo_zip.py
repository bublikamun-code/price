"""Тесты photo-ZIP: загрузка ZIP с фото серий. См. ARCHITECTURE_PLAN.md §10, §16 п.17.

Слои:
  1. Эндпоинт POST /manager/prices/photo-zip: 202 + job QUEUED + dispatch;
     не-zip файл → 415; превышение размера → 413; клиент → 403.
  2. Задача _run_photo_zip (БД реальная, S3 замокан): webp thumb/large в
     photos-series, матчинг по slug и по сырому photo_key из CSV, unmatched
     заливаются, счётчики, статусы QUEUED → RUNNING → DONE, инвалидация кэша.
  3. Zip-bomb guard (лимиты §16 п.17): файл >50 МБ / >2000 файлов → FAILED,
     никаких upload.
  4. GET /files/photo: 307 на presigned; ключ с ``..``/URL → 400; без ключа → 422.
"""
import asyncio
import io
import json
import uuid
import zipfile

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

import app.tasks.photo_zip as photo_task
from app.api.v1.manager import prices as prices_api
from app.models.catalog import Series
from app.models.enums import UserRole
from app.services import photo_zip as photo_service
from app.services.storage import StorageError
from tests.conftest import create_brand, create_series, create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


# ---------- helpers ----------

class FakeRedis:
    """In-memory Redis для job-стейта (используются только get/set с ex)."""

    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True


@pytest.fixture(autouse=True)
def _fake_job_redis(monkeypatch):
    """Весь модуль — на FakeRedis: модульный redis-клиент сервиса не должен
    открывать реальное соединение (паттерн test_export)."""
    monkeypatch.setattr(photo_service, "_redis", FakeRedis())


@pytest.fixture
def job_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(photo_service, "_redis", fake)
    return fake


@pytest.fixture
def dispatched(monkeypatch):
    """Перехват dispatch Celery-задачи (broker в тестах недоступен)."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        photo_service.run_photo_zip, "delay", lambda *a, **k: calls.append(a)
    )
    return calls


@pytest.fixture
def uploads(monkeypatch):
    """Мокаем S3: upload_fileobj (общий модуль storage у сервиса и задачи)
    складывает тело файла в список."""
    captured: list[dict] = []

    def _upload(bucket, key, fileobj, **kwargs):
        captured.append(
            {"bucket": bucket, "key": key, "body": fileobj.read(), "kwargs": kwargs}
        )

    monkeypatch.setattr(photo_task.storage, "upload_fileobj", _upload)
    return captured


async def _login(api_client, email):
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


def _png_bytes(size=(50, 30), color=(120, 140, 60)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _fake_upload(filename: str = "photos.zip", body: bytes = b"PK") -> UploadFile:
    """Минимальная заглушка UploadFile для start_photo_zip (S3 мокается тестом)."""
    return UploadFile(file=io.BytesIO(body), filename=filename,
                      headers=Headers({"content-type": "application/zip"}))


def _job_state(job_redis, job_id) -> dict:
    return json.loads(job_redis.values[f"photozip:job:{job_id}"])


async def _start_job(sf, *, manager) -> str:
    return await photo_service.start_photo_zip(user=manager, upload=_fake_upload())


def _photo_uploads(uploads: list[dict]) -> list[dict]:
    """Только заливки задачи в бакет photos-series (стартовая — tmp-uploads)."""
    return [u for u in uploads if u["bucket"] == "photos-series"]


# ===========================================================================
# 1. POST /manager/prices/photo-zip
# ===========================================================================
@pytest.mark.asyncio
class TestStartEndpoint:
    async def test_upload_202_queued_and_dispatched(
        self, api_client, session_factory, job_redis, dispatched, monkeypatch
    ):
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        await _login(api_client, MANAGER_EMAIL)
        captured = []
        monkeypatch.setattr(
            prices_api.storage,
            "upload_fileobj",
            lambda bucket, key, fileobj, **kw: captured.append((bucket, key, kw)),
        )

        r = await api_client.post(
            "/api/v1/manager/prices/photo-zip",
            files={"file": (
                "photos.zip",
                io.BytesIO(_zip_bytes({"a.jpg": _png_bytes()})),
                "application/zip",
            )},
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        assert uuid.UUID(job_id)  # валидный uuid

        # ZIP стримится в tmp-uploads под ключом photo-zip/{job_id}.zip
        assert captured == [(
            "tmp-uploads", f"photo-zip/{job_id}.zip",
            {"content_type": "application/zip"},
        )]

        # job создан в статусе QUEUED с нулевыми счётчиками
        state = _job_state(job_redis, job_id)
        assert state["status"] == "QUEUED"
        assert state["user_id"] == str(manager.id)
        assert state["files"] == 0 and state["matched"] == 0
        assert state["unmatched"] == 0 and state["errors"] == []

        # Celery-задача диспатчнулась: (job_id, user_id, s3_key)
        assert dispatched == [(job_id, str(manager.id), f"photo-zip/{job_id}.zip")]

    async def test_not_a_zip_415(self, api_client, session_factory, dispatched):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/prices/photo-zip",
            files={"file": ("photos.txt", io.BytesIO(b"just text"), "text/plain")},
        )
        assert r.status_code == 415, r.text
        assert dispatched == []

        # .zip-имя, но magic-bytes не PK
        r = await api_client.post(
            "/api/v1/manager/prices/photo-zip",
            files={"file": ("fake.zip", io.BytesIO(b"NOTPK" + b"x" * 100),
                            "application/zip")},
        )
        assert r.status_code == 415, r.text
        assert dispatched == []

    async def test_oversize_413(self, api_client, session_factory, monkeypatch):
        await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER)
        await _login(api_client, MANAGER_EMAIL)
        monkeypatch.setattr(prices_api, "_MAX_BYTES", 64)

        r = await api_client.post(
            "/api/v1/manager/prices/photo-zip",
            files={"file": ("photos.zip", io.BytesIO(b"PK" + b"x" * 200),
                            "application/zip")},
        )
        assert r.status_code == 413, r.text

    async def test_client_403(self, api_client, session_factory, dispatched):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.post(
            "/api/v1/manager/prices/photo-zip",
            files={"file": ("photos.zip", io.BytesIO(_zip_bytes({})),
                            "application/zip")},
        )
        assert r.status_code == 403, r.text
        assert dispatched == []


# ===========================================================================
# 2. Задача обработки (БД + замоканный S3)
# ===========================================================================
@pytest.mark.asyncio
class TestPhotoZipTask:
    async def test_processing_match_and_counters(
        self, session_factory, monkeypatch, job_redis, dispatched, uploads
    ):
        """Матчинг: по slug (serie_x → serie-x) и по сырому photo_key из CSV;
        unmatched-фото всё равно заливается."""
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        brand = await create_brand(session_factory, name="KEAZ")
        serie_x = await create_series(session_factory, brand=brand, name="Serie X")
        custom = await create_series(
            session_factory, brand=brand, name="Custom", photo_key="custom_photo.jpg"
        )
        job_id = await _start_job(session_factory, manager=manager)

        zip_data = _zip_bytes({
            "serie_x.jpg": _png_bytes(color=(200, 10, 10)),        # матч по slug
            "custom_photo.jpg": _png_bytes(color=(10, 200, 10)),   # матч по photo_key
            "unknown_thing.png": _png_bytes(color=(10, 10, 200)),  # unmatched
        })
        invalidated: list[tuple] = []

        async def _invalidate(*tags):
            invalidated.append(tags)
            return 0

        monkeypatch.setattr(photo_task, "invalidate_tags", _invalidate)
        monkeypatch.setattr(photo_task, "_worker_session", session_factory)
        monkeypatch.setattr(photo_task.storage, "get_bytes", lambda b, k: zip_data)

        result = await photo_task._run_photo_zip(
            uuid.UUID(job_id), str(manager.id), f"photo-zip/{job_id}.zip"
        )

        assert result["status"] == "DONE"
        assert result["files"] == 3
        assert result["matched"] == 2
        assert result["unmatched"] == 1

        # статусы: QUEUED → RUNNING → DONE; счётчики и пустой список ошибок
        state = _job_state(job_redis, job_id)
        assert state["status"] == "DONE"
        assert state["files"] == 3 and state["matched"] == 2
        assert state["unmatched"] == 1 and state["errors"] == []

        # 3 пары large+thumb с webp-ключами и content_type
        photo_uploads = _photo_uploads(uploads)
        keys = {u["key"] for u in photo_uploads}
        assert keys == {
            "photos-series/serie-x.webp",
            "photos-series/serie-x_thumb.webp",
            "photos-series/custom-photo.webp",
            "photos-series/custom-photo_thumb.webp",
            "photos-series/unknown-thing.webp",
            "photos-series/unknown-thing_thumb.webp",
        }
        assert all(u["kwargs"]["content_type"] == "image/webp" for u in photo_uploads)

        # тела — валидные webp; thumb ≤400×400, large ≤1200×1200
        # (thumbnail не увеличивает маленькие — 50×30 остаётся 50×30)
        for u in photo_uploads:
            img = Image.open(io.BytesIO(u["body"]))
            assert img.format == "WEBP"
            if "_thumb" in u["key"]:
                assert img.size <= (400, 400)
            else:
                assert img.size == (50, 30)

        # серии обновлены на ключ large; unmatched не трогал чужих
        async with session_factory() as s:
            assert (await s.get(Series, serie_x.id)).photo_key == \
                "photos-series/serie-x.webp"
            # ключ — по stem файла, хотя серия матчилась по photo_key из CSV
            assert (await s.get(Series, custom.id)).photo_key == \
                "photos-series/custom-photo.webp"

        # кэш каталога/фильтров инвалидирован (фото — часть карточек)
        assert invalidated == [("catalog", "filters")]

    async def test_corrupt_image_goes_to_errors(
        self, session_factory, monkeypatch, job_redis, dispatched, uploads
    ):
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        job_id = await _start_job(session_factory, manager=manager)
        zip_data = _zip_bytes({
            "broken.jpg": b"not an image at all",
            "good.png": _png_bytes(),
        })
        monkeypatch.setattr(photo_task, "_worker_session", session_factory)
        monkeypatch.setattr(photo_task.storage, "get_bytes", lambda b, k: zip_data)

        result = await photo_task._run_photo_zip(
            uuid.UUID(job_id), str(manager.id), f"photo-zip/{job_id}.zip"
        )

        assert result["status"] == "DONE"
        assert result["files"] == 1  # битый не посчитан
        state = _job_state(job_redis, job_id)
        assert state["files"] == 1
        assert len(state["errors"]) == 1
        assert state["errors"][0].startswith("broken.jpg:")
        # залился только good
        assert {u["key"] for u in _photo_uploads(uploads)} == {
            "photos-series/good.webp", "photos-series/good_thumb.webp",
        }

    async def test_storage_error_marks_failed(
        self, session_factory, monkeypatch, job_redis, dispatched
    ):
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        monkeypatch.setattr(
            photo_task.storage, "upload_fileobj", lambda *a, **k: None
        )
        job_id = await _start_job(session_factory, manager=manager)

        monkeypatch.setattr(photo_task, "_worker_session", session_factory)
        zip_data = _zip_bytes({"a.jpg": _png_bytes()})
        monkeypatch.setattr(photo_task.storage, "get_bytes", lambda b, k: zip_data)

        def _boom(bucket, key, fileobj, **kwargs):
            raise StorageError("minio недоступен")

        monkeypatch.setattr(photo_task.storage, "upload_fileobj", _boom)

        # sync-обёртка ловит ошибку → FAILED в Redis, worker не падает
        # (to_thread: обёртка зовёт asyncio.run — нельзя в loop текущего теста)
        res = await asyncio.to_thread(
            photo_task.run_photo_zip, job_id, str(manager.id), f"photo-zip/{job_id}.zip"
        )
        assert res["status"] == "FAILED"
        state = _job_state(job_redis, job_id)
        assert state["status"] == "FAILED"
        assert "minio" in state["error"]


# ===========================================================================
# 3. Zip-bomb guard (лимиты §16 п.17)
# ===========================================================================
@pytest.mark.asyncio
class TestZipLimits:
    async def _run_wrapper(self, sf, monkeypatch, *, manager, job_id, zip_data):
        """Прогон через sync-обёртку задачи: guard → FAILED в Redis."""
        monkeypatch.setattr(photo_task, "_worker_session", sf)
        monkeypatch.setattr(photo_task.storage, "get_bytes", lambda b, k: zip_data)
        return await asyncio.to_thread(
            photo_task.run_photo_zip, job_id, str(manager.id), f"photo-zip/{job_id}.zip"
        )

    async def test_per_file_limit_failed_no_uploads(
        self, session_factory, monkeypatch, job_redis, dispatched, uploads
    ):
        """Файл 60 МБ нулей (сжимается отлично) превышает лимит 50 МБ/файл."""
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        job_id = await _start_job(session_factory, manager=manager)
        zip_data = _zip_bytes({
            "small.jpg": _png_bytes(),
            "bomb.jpg": b"\x00" * (60 * 1024 * 1024),
        })

        res = await self._run_wrapper(session_factory, monkeypatch, manager=manager,
                                      job_id=job_id, zip_data=zip_data)

        assert res["status"] == "FAILED"
        assert "50 МБ" in res["error"]
        state = _job_state(job_redis, job_id)
        assert state["status"] == "FAILED"
        assert "50 МБ" in state["error"]
        assert _photo_uploads(uploads) == []  # ни одного upload до нарушения

    async def test_too_many_files_failed(
        self, session_factory, monkeypatch, job_redis, dispatched, uploads
    ):
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        job_id = await _start_job(session_factory, manager=manager)
        zip_data = _zip_bytes({f"f{i}.jpg": b"x" for i in range(2001)})

        res = await self._run_wrapper(session_factory, monkeypatch, manager=manager,
                                      job_id=job_id, zip_data=zip_data)

        assert res["status"] == "FAILED"
        assert "2000" in res["error"]
        assert _job_state(job_redis, job_id)["status"] == "FAILED"
        assert _photo_uploads(uploads) == []

    async def test_non_image_files_skipped(
        self, session_factory, monkeypatch, job_redis, dispatched, uploads
    ):
        manager = await create_user(
            session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER
        )
        job_id = await _start_job(session_factory, manager=manager)
        zip_data = _zip_bytes({
            "readme.txt": b"hello",
            "photo.jpg": _png_bytes(),
        })
        monkeypatch.setattr(photo_task, "_worker_session", session_factory)
        monkeypatch.setattr(photo_task.storage, "get_bytes", lambda b, k: zip_data)

        result = await photo_task._run_photo_zip(
            uuid.UUID(job_id), str(manager.id), f"photo-zip/{job_id}.zip"
        )

        assert result["files"] == 1
        assert {u["key"] for u in _photo_uploads(uploads)} == {
            "photos-series/photo.webp", "photos-series/photo_thumb.webp",
        }


# ===========================================================================
# 4. GET /files/photo
# ===========================================================================
@pytest.mark.asyncio
class TestFilesPhotoEndpoint:
    async def test_redirect_307_to_presigned(
        self, api_client, session_factory, monkeypatch
    ):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)
        import app.api.v1.files as files_api

        monkeypatch.setattr(
            files_api.storage,
            "presigned_get",
            lambda bucket, key, **kw: f"http://minio.local/{key}",
        )

        r = await api_client.get(
            "/api/v1/files/photo", params={"key": "photos-series/serie-x.webp"}
        )
        assert r.status_code == 307, r.text
        assert r.headers["location"] == "http://minio.local/photos-series/serie-x.webp"

    async def test_traversal_and_url_keys_400(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get(
            "/api/v1/files/photo", params={"key": "../secret/keys.pem"}
        )
        assert r.status_code == 400, r.text

        # URL вместо «голого» пути тоже недопустим
        r = await api_client.get(
            "/api/v1/files/photo",
            params={"key": "https://evil.example.com/photos/a.webp"},
        )
        assert r.status_code == 400, r.text

    async def test_missing_key_422(self, api_client, session_factory):
        await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT)
        await _login(api_client, CLIENT_EMAIL)

        r = await api_client.get("/api/v1/files/photo")
        assert r.status_code == 422, r.text

    async def test_requires_auth(self, api_client):
        r = await api_client.get(
            "/api/v1/files/photo", params={"key": "photos-series/a.webp"}
        )
        assert r.status_code == 401, r.text
