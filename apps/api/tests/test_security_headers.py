"""FP-11: security-заголовки API для Bearer-клиентов.

CORP same-origin ставится на все ответы API; ``Cache-Control: no-store`` —
на аутентифицированные, причём не только по cookie (web), но и по
Authorization (нативные клиенты). /healthz — публичный и лёгкий, на нём и
проверяем: middleware один на всё приложение, эндпоинт значения не имеет.
"""
from fastapi.testclient import TestClient

import pytest

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # /healthz не трогает БД — TestClient на живом app без оверрайдов,
    # как в test_health.py. Middleware заголовков один на приложение.
    return TestClient(app)


def test_corp_on_every_response(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["cross-origin-resource-policy"] == "same-origin"


def test_no_store_for_bearer_client(client: TestClient) -> None:
    r = client.get("/healthz", headers={"Authorization": "Bearer some-token"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_no_store_kept_for_cookie_session(client: TestClient) -> None:
    # Web-клиент ходит с HttpOnly-кукой access-токена — прежнее поведение.
    r = client.get("/healthz", cookies={"auth_token": "some-token"})
    assert r.headers["cache-control"] == "no-store"


def test_no_store_absent_for_anonymous(client: TestClient) -> None:
    r = client.get("/healthz")
    assert "no-store" not in r.headers.get("cache-control", "")
