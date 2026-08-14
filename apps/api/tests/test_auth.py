"""Интеграционные тесты аутентификации и RBAC. См. ARCHITECTURE_PLAN.md §6, §11.

Покрытие:
  - login: успех, неверный пароль, неактивный пользователь, case-insensitive email
  - /me: с токеном, без токена (401), с кривым токеном (401)
  - refresh: rotation, повторное использование старого refresh (401)
  - logout: отзыв сессии, /me после logout (401)
  - RBAC: клиент → /manager/ping (403), менеджер → 200
  - rate-limit: 6-я попытка login → 429
"""
import pytest

from app.core.limiter import limiter
from app.models.enums import UserRole
from app.schemas.auth import TokenPair
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


# ---------- helpers ----------
async def _login(api_client, email: str, password: str = PASSWORD):
    return await api_client.post("/api/v1/auth/login", json={"email": email, "password": password})


# =========================================================
# LOGIN
# =========================================================
def test_token_pair_keeps_refresh_internal():
    pair = TokenPair(access_token="access", refresh_token="refresh", expires_in=60)
    assert pair.refresh_token == "refresh"
    assert "refresh_token" not in pair.model_dump()


async def test_login_success(api_client, session_factory):
    await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    r = await _login(api_client, MANAGER_EMAIL, PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh_token" not in body
    assert body["expires_in"] > 0
    # cookies установлены
    assert "access_token" in r.cookies
    assert "refresh_token" in r.cookies


async def test_login_wrong_password(api_client, session_factory):
    await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    r = await _login(api_client, MANAGER_EMAIL, "wrong")
    assert r.status_code == 401


async def test_login_unknown_user(api_client):
    r = await _login(api_client, "nobody@example.by", PASSWORD)
    assert r.status_code == 401


async def test_login_inactive_user(api_client, session_factory):
    from app.models.user import User
    async with session_factory() as s:
        from app.core.security import hash_password
        u = User(email=MANAGER_EMAIL, password_hash=hash_password(PASSWORD),
                 full_name="X", role=UserRole.MANAGER, is_active=False)
        s.add(u)
        await s.commit()
    r = await _login(api_client, MANAGER_EMAIL, PASSWORD)
    assert r.status_code == 401


async def test_login_email_case_insensitive(api_client, session_factory):
    """CITEXT: регистр email не важит."""
    await create_user(session_factory, email="User@Example.com", role=UserRole.CLIENT, password=PASSWORD)
    r = await _login(api_client, "user@example.com", PASSWORD)
    assert r.status_code == 200


# =========================================================
# /ME
# =========================================================
async def test_me_with_token(api_client, session_factory):
    user = await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == CLIENT_EMAIL
    assert body["role"] == "CLIENT"
    assert body["consent_accepted"] is False
    assert body["id"] == str(user.id)


async def test_me_without_token(api_client):
    r = await api_client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_with_bad_token(api_client):
    r = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert r.status_code == 401


# =========================================================
# REFRESH (rotation)
# =========================================================
async def test_refresh_rotation_and_old_invalid(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    r1 = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    refresh_old = r1.cookies["refresh_token"]

    r2 = await api_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text
    refresh_new = r2.cookies["refresh_token"]
    assert refresh_new != refresh_old  # rotation: новый токен

    # Старый refresh больше не валиден
    api_client.cookies.set("refresh_token", refresh_old)
    r3 = await api_client.post("/api/v1/auth/refresh")
    assert r3.status_code == 401

    # Новый — валиден
    api_client.cookies.set("refresh_token", refresh_new)
    r4 = await api_client.post("/api/v1/auth/refresh")
    assert r4.status_code == 200


async def test_refresh_from_cookie(api_client, session_factory):
    """Без тела — refresh берётся из httpOnly cookie."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


# =========================================================
# LOGOUT
# =========================================================
async def test_logout_revokes_session(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    r1 = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    refresh = r1.cookies["refresh_token"]

    r2 = await api_client.post("/api/v1/auth/logout")
    assert r2.status_code == 204
    assert "refresh_token" not in r2.cookies

    # refresh после logout не работает
    api_client.cookies.set("refresh_token", refresh)
    r3 = await api_client.post("/api/v1/auth/refresh")
    assert r3.status_code == 401


# =========================================================
# RBAC
# =========================================================
async def test_rbac_client_forbidden_manager(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.get("/api/v1/manager/ping")
    assert r.status_code == 403, r.text


async def test_rbac_manager_allowed(api_client, session_factory):
    await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL, PASSWORD)
    r = await api_client.get("/api/v1/manager/ping")
    assert r.status_code == 200, r.text
    assert r.json()["manager"] == MANAGER_EMAIL


async def test_rbac_unauthenticated(api_client):
    r = await api_client.get("/api/v1/manager/ping")
    assert r.status_code == 401


# =========================================================
# RATE LIMIT
# =========================================================
@pytest.mark.asyncio
async def test_login_rate_limit(api_client, session_factory):
    """При лимите 5/15мин 6-я попытка → 429. Лимит перенастраивается на маленький."""
    await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    limiter.enabled = True
    try:
        # Перезаписывать декорированный лимит через временное приложение не нужно —
        # используем дефолтный 5/15min: первые 5 → 401 (wrong pwd), 6-я → 429.
        statuses = []
        for _ in range(6):
            r = await api_client.post(
                "/api/v1/auth/login",
                json={"email": MANAGER_EMAIL, "password": "wrong"},
            )
            statuses.append(r.status_code)
        # первые 5 — 401 (неверный пароль, но лимит ещё не превышен)
        assert statuses[:5] == [401] * 5, statuses
        # 6-я — 429 (rate limit)
        assert statuses[5] == 429, statuses
    finally:
        limiter.enabled = False
        # сброс хранилища, чтобы не влиять на другие тесты
        try:
            limiter.reset()
        except Exception:
            pass
