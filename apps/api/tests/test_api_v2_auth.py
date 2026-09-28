"""Нативная аутентификация API v2. См. ARCHITECTURE_PLAN.md §16 п.36,
docs/NATIVE_API_CONTRACT.md §4, docs/API_V2_CONTRACT.md §6.

Покрытие:
  - grant: токены в теле (не cookie), device/os/appVersion пишутся в сессию
  - неверные креды → problem+json с кодом INVALID_CREDENTIALS
  - 2FA: login без токенов, verify выдаёт grant; метаданные — тоже
  - refresh из тела: ротация, reuse detection, никакого CSRF
  - Bearer-аутентифицированный journal: устройства, current, отзыв
  - logout по sid из access-JWT
"""
import uuid
from datetime import datetime, timedelta, timezone

import hashlib
import jwt
import pyotp

from app.core.config import settings
from app.core.security import create_access_token
from app.models.enums import UserRole
from app.models.user import Session as SessionModel
from app.models.user import User
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
EMAIL = "native@example.by"
TOTP_SECRET = pyotp.random_base32()


async def _user(session_factory, *, totp: bool = False) -> User:
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.CLIENT, password=PASSWORD
    )
    if totp:
        async with session_factory() as s:
            row = await s.get(User, user.id)
            row.totp_secret = TOTP_SECRET
            await s.commit()
    return user


async def _login(api_client, **overrides):
    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "clientType": "NATIVE",
        "deviceName": "iPhone 15 Pro",
        "os": "iOS 18.2",
        "appVersion": "1.0.0",
    }
    payload.update(overrides)
    return await api_client.post("/api/v2/auth/sessions", json=payload)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# =========================================================
# GRANT
# =========================================================
async def test_native_grant_returns_tokens_in_body_not_cookies(api_client, session_factory):
    await _user(session_factory)
    r = await _login(api_client)
    assert r.status_code == 200, r.text
    assert "set-cookie" not in r.headers
    data = r.json()["data"]
    assert data["accessToken"]
    assert data["refreshToken"]
    assert data["accessTokenExpiresAt"] > data["session"]["createdAt"]
    assert data["session"]["current"] is True
    assert data["session"]["clientType"] == "NATIVE"
    assert data["user"]["email"] == EMAIL


async def test_native_grant_persists_device_metadata(api_client, session_factory):
    """§16 п.36: журнал сессий обязан отличать устройства, а не показывать User-Agent."""
    await _user(session_factory)
    r = await _login(api_client)
    session_id = r.json()["data"]["session"]["id"]

    async with session_factory() as s:
        row = await s.get(SessionModel, uuid.UUID(session_id))
        assert row.client_type == "NATIVE"
        assert row.device_name == "iPhone 15 Pro"
        assert row.os_name == "iOS 18.2"
        assert row.app_version == "1.0.0"


async def test_web_grant_keeps_native_columns_null(api_client, session_factory):
    """clientType=WEB не должен изображать устройство — колонки остаются NULL."""
    await _user(session_factory)
    r = await _login(api_client, clientType="WEB", deviceName="Chrome", os="Windows", appVersion=None)
    data = r.json()["data"]
    assert data["session"]["deviceName"] is None
    assert data["session"]["clientType"] == "WEB"


async def test_native_grant_wrong_password_is_problem_json(api_client, session_factory):
    await _user(session_factory)
    r = await _login(api_client, password="wrong-password")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "INVALID_CREDENTIALS"
    assert body["status"] == 401
    assert body["requestId"]


async def test_native_grant_unknown_email_same_error(api_client, session_factory):
    await _user(session_factory)
    wrong = await _login(api_client, password="nope")
    unknown = await _login(api_client, email="nobody@example.by", password="nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


# =========================================================
# 2FA
# =========================================================
async def test_native_2fa_login_returns_challenge_without_tokens(api_client, session_factory):
    await _user(session_factory, totp=True)
    r = await _login(api_client)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["twoFaRequired"] is True
    assert data["ticket"]
    assert "accessToken" not in data
    assert "refreshToken" not in data


async def test_native_2fa_verify_grants_session_with_metadata(api_client, session_factory):
    await _user(session_factory, totp=True)
    ticket = (await _login(api_client)).json()["data"]["ticket"]

    r = await api_client.post(
        "/api/v2/auth/2fa/challenges/verify",
        json={
            "ticket": ticket,
            "code": pyotp.TOTP(TOTP_SECRET).now(),
            "deviceName": "Pixel 9",
            "os": "Android 15",
            "appVersion": "1.0.0",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["accessToken"] and data["refreshToken"]
    assert data["session"]["deviceName"] == "Pixel 9"
    assert data["session"]["os"] == "Android 15"


async def test_native_2fa_verify_wrong_code_is_unauthorized(api_client, session_factory):
    await _user(session_factory, totp=True)
    ticket = (await _login(api_client)).json()["data"]["ticket"]
    r = await api_client.post(
        "/api/v2/auth/2fa/challenges/verify",
        json={"ticket": ticket, "code": "000000"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


# =========================================================
# REFRESH
# =========================================================
async def test_native_refresh_rotates_from_body(api_client, session_factory):
    await _user(session_factory)
    first = (await _login(api_client)).json()["data"]

    r = await api_client.post(
        "/api/v2/auth/sessions/refresh",
        json={"refreshToken": first["refreshToken"]},
    )
    assert r.status_code == 200, r.text
    second = r.json()["data"]
    assert second["refreshToken"] != first["refreshToken"]
    assert second["session"]["id"] != first["session"]["id"]


async def test_native_refresh_needs_no_csrf_header(api_client, session_factory):
    """Bearer-клиент не владеет cookie — требовать X-CSRF-Token было бы блокировкой."""
    await _user(session_factory)
    first = (await _login(api_client)).json()["data"]
    r = await api_client.post(
        "/api/v2/auth/sessions/refresh",
        json={"refreshToken": first["refreshToken"]},
    )
    assert r.status_code == 200


async def test_native_refresh_rejects_reused_token(api_client, session_factory):
    """Reuse detection: второй раз старый refresh после grace-окна → 401."""
    from app.core.config import settings as _settings

    await _user(session_factory)
    first = (await _login(api_client)).json()["data"]
    await api_client.post(
        "/api/v2/auth/sessions/refresh", json={"refreshToken": first["refreshToken"]}
    )
    # В пределах grace-окна старый токен ещё «догоняет» цепочку — это задокументированное
    # поведение, поэтому выходим за окно перед повторной попыткой.
    original = _settings.refresh_grace_seconds
    _settings.refresh_grace_seconds = 0
    try:
        r = await api_client.post(
            "/api/v2/auth/sessions/refresh", json={"refreshToken": first["refreshToken"]}
        )
    finally:
        _settings.refresh_grace_seconds = original
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


async def test_native_refresh_unknown_token_is_unauthorized(api_client, session_factory):
    await _user(session_factory)
    r = await api_client.post(
        "/api/v2/auth/sessions/refresh", json={"refreshToken": "not-a-real-token"}
    )
    assert r.status_code == 401


# =========================================================
# ЖУРНАЛ СЕССИЙ
# =========================================================
async def test_session_journal_lists_devices_and_marks_current(api_client, session_factory):
    await _user(session_factory)
    phone = (await _login(api_client)).json()["data"]
    r = await api_client.get(
        "/api/v2/auth/sessions", headers=_auth(phone["accessToken"])
    )
    assert r.status_code == 200
    sessions = r.json()["data"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == phone["session"]["id"]
    assert sessions[0]["deviceName"] == "iPhone 15 Pro"
    assert sessions[0]["current"] is True

    second = (await _login(api_client, deviceName="iPad", os="iPadOS 18.2")).json()["data"]
    journal = (
        await api_client.get("/api/v2/auth/sessions", headers=_auth(second["accessToken"]))
    ).json()["data"]
    assert len(journal) == 2
    assert [s["current"] for s in journal] == [True, False]


async def test_session_journal_requires_authentication(api_client, session_factory):
    await _user(session_factory)
    r = await api_client.get("/api/v2/auth/sessions")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_revoke_one_session_by_id(api_client, session_factory):
    await _user(session_factory)
    keep = (await _login(api_client, deviceName="iPhone")).json()["data"]
    drop = (await _login(api_client, deviceName="iPad")).json()["data"]

    r = await api_client.delete(
        f"/api/v2/auth/sessions/{drop['session']['id']}", headers=_auth(keep["accessToken"])
    )
    assert r.status_code == 204

    journal = (
        await api_client.get("/api/v2/auth/sessions", headers=_auth(keep["accessToken"]))
    ).json()["data"]
    assert [s["id"] for s in journal] == [keep["session"]["id"]]


async def test_revoke_foreign_session_is_not_found(api_client, session_factory):
    await _user(session_factory)
    own = (await _login(api_client)).json()["data"]
    other = await create_user(session_factory, email="other@example.by", role=UserRole.CLIENT)
    async with session_factory() as s:
        foreign = SessionModel(
            user_id=other.id,
            refresh_token_hash=hashlib.sha256(b"x").hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            revoked=False,
        )
        s.add(foreign)
        await s.commit()
        await s.refresh(foreign)
        foreign_id = foreign.id

    r = await api_client.delete(
        f"/api/v2/auth/sessions/{foreign_id}", headers=_auth(own["accessToken"])
    )
    assert r.status_code == 404
    assert r.json()["code"] == "RESOURCE_NOT_FOUND"


# =========================================================
# LOGOUT
# =========================================================
async def test_logout_revokes_session_identified_by_access_token_sid(api_client, session_factory):
    await _user(session_factory)
    grant = (await _login(api_client)).json()["data"]

    r = await api_client.delete(
        "/api/v2/auth/sessions/current", headers=_auth(grant["accessToken"])
    )
    assert r.status_code == 204

    # Сессия отозвана: следующий refresh с её refresh-токеном больше не работает,
    # а access-токен проверяется по живости сессии и тоже перестаёт проходить.
    refreshed = await api_client.post(
        "/api/v2/auth/sessions/refresh", json={"refreshToken": grant["refreshToken"]}
    )
    assert refreshed.status_code == 401
    assert (await api_client.get("/api/v2/auth/sessions", headers=_auth(grant["accessToken"]))).status_code == 401


async def test_logout_requires_authentication(api_client, session_factory):
    await _user(session_factory)
    r = await api_client.delete("/api/v2/auth/sessions/current")
    assert r.status_code == 401


async def test_logout_rejects_access_token_without_sid(api_client, session_factory):
    """Токен без sid не позволяет однозначно назвать «текущую» сессию → 401, а не 500."""
    user = await _user(session_factory)
    token = create_access_token(subject=str(user.id), extra={"role": user.role.value})
    r = await api_client.delete("/api/v2/auth/sessions/current", headers=_auth(token))
    assert r.status_code == 401
    assert r.json()["code"] == "AUTHENTICATION_REQUIRED"


async def test_access_token_sid_matches_created_session(api_client, session_factory):
    """Контракт v2: sid в access-JWT = id выданной сессии (logout это использует)."""
    await _user(session_factory)
    grant = (await _login(api_client)).json()["data"]

    payload = jwt.decode(
        grant["accessToken"], settings.jwt_verify_key, algorithms=[settings.jwt_algorithm]
    )
    assert payload["sid"] == grant["session"]["id"]
    # refresh не должен попадать в access-токен (§6.3)
    assert "refresh" not in payload
