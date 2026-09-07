"""Тесты /readyz: readiness проверяет все компоненты (БД + Redis + S3).

Ответ 200 только если всё живо; при деградации — 503 и перечень отказавших
компонент в ``checks``. Redis/S3 мокаются на уровне модуля health (реальных
соединений в тестах нет — см. conftest._isolated_cache).
"""
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import health as health_api
from app.db.session import get_db
from app.main import app
from app.services.storage import StorageError

CHECKS_OK = {"db": "ok", "redis": "ok", "s3": "ok"}


class FakeProbeRedis:
    """Стаб redis-клиента для пробы ping."""

    def __init__(self, exc: Exception | None = None):
        self._exc = exc

    async def ping(self) -> bool:
        if self._exc is not None:
            raise self._exc
        return True


def _patch_ok(monkeypatch) -> None:
    monkeypatch.setattr(health_api, "_readiness_redis", FakeProbeRedis())
    monkeypatch.setattr(health_api.storage, "check_connection", lambda: None)


class _BrokenDBSession:
    """Сессия, у которой любой execute падает (БД недоступна)."""

    async def execute(self, *args, **kwargs):
        raise SQLAlchemyError("db down")


@pytest.mark.asyncio
class TestReadyz:
    async def test_all_components_ok_200(self, api_client, monkeypatch):
        _patch_ok(monkeypatch)
        r = await api_client.get("/readyz")
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "checks": CHECKS_OK}

    async def test_redis_down_503(self, api_client, monkeypatch):
        _patch_ok(monkeypatch)
        monkeypatch.setattr(
            health_api,
            "_readiness_redis",
            FakeProbeRedis(ConnectionError("redis недоступен")),
        )
        r = await api_client.get("/readyz")
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["status"] == "fail"
        assert body["checks"] == {"db": "ok", "redis": "fail", "s3": "ok"}

    async def test_s3_down_503(self, api_client, monkeypatch):
        _patch_ok(monkeypatch)

        def _boom():
            raise StorageError("Хранилище S3 недоступно")

        monkeypatch.setattr(health_api.storage, "check_connection", _boom)
        r = await api_client.get("/readyz")
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["status"] == "fail"
        assert body["checks"] == {"db": "ok", "redis": "ok", "s3": "fail"}

    async def test_db_down_503(self, api_client, monkeypatch):
        _patch_ok(monkeypatch)

        async def _broken_db():
            yield _BrokenDBSession()

        app.dependency_overrides[get_db] = _broken_db
        try:
            r = await api_client.get("/readyz")
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["status"] == "fail"
        assert body["checks"] == {"db": "fail", "redis": "ok", "s3": "ok"}

    async def test_multiple_failures_listed(self, api_client, monkeypatch):
        _patch_ok(monkeypatch)
        monkeypatch.setattr(
            health_api,
            "_readiness_redis",
            FakeProbeRedis(ConnectionError("redis недоступен")),
        )

        def _boom():
            raise StorageError("Хранилище S3 недоступно")

        monkeypatch.setattr(health_api.storage, "check_connection", _boom)
        r = await api_client.get("/readyz")
        assert r.status_code == 503, r.text
        body = r.json()
        assert body["checks"] == {"db": "ok", "redis": "fail", "s3": "fail"}
