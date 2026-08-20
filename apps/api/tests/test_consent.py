"""Тесты согласия на обработку ПДн через PATCH /auth/me (§16 п.20-6, §6)."""
from sqlalchemy import select

from app.models.enums import UserRole
from app.models.user import ConsentLog
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
UA = "zcode-test-agent/1.0"


async def _login(api_client, email):
    r = await api_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def _consent_logs(session_factory, user_id) -> list[ConsentLog]:
    async with session_factory() as s:
        res = await s.execute(select(ConsentLog).where(ConsentLog.user_id == user_id))
        return list(res.scalars().all())


async def test_accept_consent_logs_ip_and_user_agent(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.patch(
        "/api/v1/auth/me",
        json={"consent_accepted": True},
        headers={"User-Agent": UA},
    )
    assert r.status_code == 200, r.text
    assert r.json()["consent_accepted"] is True

    logs = await _consent_logs(sf, user.id)
    assert len(logs) == 1
    assert logs[0].policy_version == "1.0"
    assert logs[0].ip == "127.0.0.1"  # httpx ASGITransport default
    assert logs[0].user_agent == UA
    assert logs[0].accepted_at is not None


async def test_accept_consent_idempotent(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    for _ in range(2):
        r = await api_client.patch("/api/v1/auth/me", json={"consent_accepted": True})
        assert r.status_code == 200, r.text
        assert r.json()["consent_accepted"] is True

    assert len(await _consent_logs(sf, user.id)) == 1


async def test_consent_cannot_be_revoked(api_client, session_factory):
    sf = session_factory
    user = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.patch("/api/v1/auth/me", json={"consent_accepted": False})
    assert r.status_code == 422
    assert "Согласие" in r.json()["detail"]
    assert len(await _consent_logs(sf, user.id)) == 0


async def test_consent_false_rejected_even_if_already_accepted(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.patch("/api/v1/auth/me", json={"consent_accepted": True})
    assert r.status_code == 200

    r = await api_client.patch("/api/v1/auth/me", json={"consent_accepted": False})
    assert r.status_code == 422


async def test_display_currency_regression(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.patch("/api/v1/auth/me", json={"display_currency": "usd"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_currency"] == "USD"
    assert body["consent_accepted"] is False  # не задано — не меняется


async def test_empty_patch_still_422(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)

    r = await api_client.patch("/api/v1/auth/me", json={})
    assert r.status_code == 422
