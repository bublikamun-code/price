"""Smoke-тесты health-эндпоинтов. Полный набор тестов — по этапам (§13)."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.limiter import limiter
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["app"] == "B2B Price Portal"


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_published(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "B2B Price Portal API"


def test_redis_url_uses_configured_connection_fields() -> None:
    configured = Settings(redis_host="cache.internal", redis_port=6380, redis_db=4)

    assert configured.redis_url == "redis://cache.internal:6380/4"


def test_rate_limiter_uses_redis_storage() -> None:
    assert limiter._storage_uri.startswith("redis://")
