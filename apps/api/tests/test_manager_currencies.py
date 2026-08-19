"""Тесты курсов валют менеджер-панели. См. §6, §17, §16 п.19."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.enums import UserRole
from app.models.pricing import ExchangeRate
from app.models.system import AuditLog
from tests.conftest import create_user, set_rate

PASSWORD = "Passw0rd!"
MANAGER_EMAIL = "manager@example.by"
CLIENT_EMAIL = "client@example.by"


async def _login_manager(api_client, sf):
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": MANAGER_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return manager


async def test_currencies_require_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await api_client.post("/api/v1/auth/login", json={"email": CLIENT_EMAIL, "password": PASSWORD})
    assert (await api_client.get("/api/v1/manager/currencies/rates")).status_code == 403
    assert (
        await api_client.post(
            "/api/v1/manager/currencies/rate",
            json={"currency_code": "USD", "rate": "3"},
        )
    ).status_code == 403


async def test_set_manual_rate_upserts_same_day(api_client, session_factory):
    sf = session_factory
    manager = await _login_manager(api_client, sf)

    r = await api_client.post(
        "/api/v1/manager/currencies/rate", json={"currency_code": "USD", "rate": "2.5"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "MANUAL"
    assert body["is_manual"] is True
    assert body["fetched_at"] == date.today().isoformat()
    assert Decimal(body["rate"]) == Decimal("2.5")

    r = await api_client.post(
        "/api/v1/manager/currencies/rate", json={"currency_code": "USD", "rate": "2.6"}
    )
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["rate"]) == Decimal("2.6")

    r = await api_client.get("/api/v1/manager/currencies/rates")
    assert r.status_code == 200
    manual_rows = [
        row for row in r.json()["data"]
        if row["source"] == "MANUAL" and row["fetched_at"] == date.today().isoformat()
    ]
    assert len(manual_rows) == 1
    assert Decimal(manual_rows[0]["rate"]) == Decimal("2.6")

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog)
            .where(AuditLog.action == "currency.rate.manual")
            .order_by(AuditLog.created_at.desc())
        )).scalars().all()
    assert len(entries) == 2
    assert entries[0].actor_id == manager.id
    assert Decimal(entries[0].after["rate"]) == Decimal("2.6")
    assert Decimal(entries[-1].after["rate"]) == Decimal("2.5")


async def test_set_manual_rate_rejects_byn(api_client, session_factory):
    await _login_manager(api_client, session_factory)
    r = await api_client.post(
        "/api/v1/manager/currencies/rate", json={"currency_code": "BYN", "rate": "1"}
    )
    assert r.status_code == 422


async def test_set_manual_rate_explicit_date(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    yesterday = date.today() - timedelta(days=1)
    r = await api_client.post(
        "/api/v1/manager/currencies/rate",
        json={"currency_code": "EUR", "rate": "3.4", "fetched_at": yesterday.isoformat()},
    )
    assert r.status_code == 201, r.text
    assert r.json()["fetched_at"] == yesterday.isoformat()

    async with sf() as s:
        row = await s.scalar(
            select(ExchangeRate).where(
                ExchangeRate.currency_code == "EUR", ExchangeRate.source == "MANUAL"
            )
        )
    assert row is not None and row.fetched_at == yesterday


async def test_rates_window_7_days(api_client, session_factory):
    sf = session_factory
    today = date.today()
    await set_rate(sf, currency="USD", rate=Decimal("3.0"), fetched_at=today)
    await set_rate(sf, currency="USD", rate=Decimal("2.9"), fetched_at=today - timedelta(days=5))
    await set_rate(sf, currency="USD", rate=Decimal("2.8"), fetched_at=today - timedelta(days=8))
    await set_rate(sf, currency="EUR", rate=Decimal("3.5"), fetched_at=today)
    await set_rate(sf, currency="BYN", rate=Decimal("1"), fetched_at=today)

    await _login_manager(api_client, sf)
    r = await api_client.get("/api/v1/manager/currencies/rates")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    currencies = [row["currency_code"] for row in data]
    assert set(currencies) == {"USD", "EUR"}  # BYN не отслеживается, старый курс вне окна
    usd_rates = {Decimal(row["rate"]) for row in data if row["currency_code"] == "USD"}
    assert usd_rates == {Decimal("3.0"), Decimal("2.9")}

    # сортировка: валюта asc
    assert data[0]["currency_code"] == "EUR"


async def test_refresh_queues_celery_task(api_client, session_factory, monkeypatch):
    await _login_manager(api_client, session_factory)

    import app.tasks.fetch_nbrb_rates as fetch_task_module

    calls: list[bool] = []

    def _fake_delay():
        calls.append(True)

    monkeypatch.setattr(fetch_task_module.fetch_rates, "delay", _fake_delay)

    r = await api_client.post("/api/v1/manager/currencies/refresh")
    assert r.status_code == 202, r.text
    assert r.json() == {"queued": True}
    assert calls == [True]
