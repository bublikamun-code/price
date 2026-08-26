"""Тесты клиентов менеджер-панели. См. §6, §16 п.19, §11 (RBAC, audit_log)."""
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.enums import UserRole
from app.models.pricing import UserBrand
from app.models.system import AuditLog, Notification
from app.models.user import Session as SessionModel
from tests.conftest import (
    create_brand,
    create_product,
    create_series,
    create_user,
    set_discount,
    set_rate,
)

PASSWORD = "Passw0rd!"
CLIENT_EMAIL = "client@example.by"
MANAGER_EMAIL = "manager@example.by"


async def _login(api_client, email, password=PASSWORD):
    return await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


async def _seed(sf, *, client_email=CLIENT_EMAIL):
    """Менеджер + клиент; возвращает (manager, client)."""
    manager = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    client = await create_user(sf, email=client_email, role=UserRole.CLIENT, password=PASSWORD)
    return manager, client


async def _login_manager(api_client, sf):
    manager, client = await _seed(sf)
    r = await _login(api_client, MANAGER_EMAIL)
    assert r.status_code == 200, r.text
    return manager, client


# ------------------------------------------------------------------- RBAC
async def test_users_require_manager_role(api_client, session_factory):
    sf = session_factory
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.get("/api/v1/manager/users")).status_code == 403
    assert (
        await api_client.post(
            "/api/v1/manager/users", json={"email": "new@x.by", "full_name": "New"}
        )
    ).status_code == 403


# ----------------------------------------------------------------- create
async def test_create_client_with_temp_password(api_client, session_factory):
    sf = session_factory
    manager, _ = await _login_manager(api_client, sf)

    r = await api_client.post(
        "/api/v1/manager/users",
        json={
            "email": "New.Client@Example.by",
            "full_name": "ООО Ромашка",
            "company": "Ромашка",
            "phone": "+375291234567",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    temp_password = body["temp_password"]
    assert temp_password
    assert body["user"]["email"] == "new.client@example.by"
    assert body["user"]["is_active"] is True
    assert body["user"]["fixed_rate"] is None

    assert (await _login(api_client, "new.client@example.by", temp_password)).status_code == 200

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "user.create")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].actor_id == manager.id
    assert entries[0].target_type == "user"
    assert entries[0].after["email"] == "new.client@example.by"

    async with sf() as s:
        notifs = (await s.execute(
            select(Notification).where(Notification.type == "ACCOUNT_CREATED")
        )).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].user_id == uuid.UUID(body["user"]["id"])
    assert temp_password not in (notifs[0].body or "")
    assert temp_password not in (notifs[0].title or "")


async def test_create_client_duplicate_email_conflict(api_client, session_factory):
    sf = session_factory
    await _login_manager(api_client, sf)
    r = await api_client.post(
        "/api/v1/manager/users",
        json={"email": CLIENT_EMAIL.upper(), "full_name": "Дубль"},
    )
    assert r.status_code == 409


async def test_create_client_discount_percent_all(api_client, session_factory):
    sf = session_factory
    brand_a = await create_brand(sf, name="Alpha")
    brand_b = await create_brand(sf, name="Beta")
    await _login_manager(api_client, sf)

    r = await api_client.post(
        "/api/v1/manager/users",
        json={
            "email": "disc@example.by",
            "full_name": "Скидочник",
            "discount_percent_all": "7.50",
        },
    )
    assert r.status_code == 201, r.text
    user_id = uuid.UUID(r.json()["user"]["id"])

    async with sf() as s:
        rows = (await s.execute(
            select(UserBrand).where(UserBrand.user_id == user_id)
        )).scalars().all()
    assert {r.brand_id for r in rows} == {brand_a.id, brand_b.id}
    assert all(Decimal(str(r.discount_percent)) == Decimal("7.5") for r in rows)


# ------------------------------------------------------------------- list
async def test_list_users_with_aggregates(api_client, session_factory):
    sf = session_factory
    brand_a = await create_brand(sf, name="Alpha")
    brand_b = await create_brand(sf, name="Beta")
    series = await create_series(sf, brand=brand_a, name="Serie X")
    await create_product(sf, sku="A-1", name="Widget", brand=brand_a, series=series)

    manager, client1 = await _seed(sf, client_email="one@example.by")
    await create_user(sf, email="two@example.by", role=UserRole.CLIENT, password=PASSWORD)

    await set_discount(sf, user=client1, brand=brand_a, percent=10)
    await set_discount(sf, user=client1, brand=brand_b, percent=20)

    await _login(api_client, "one@example.by")
    r = await api_client.post("/api/v1/orders", json={"items": [{"sku": "A-1", "quantity": 1}], "delivery_point": "Склад Минск"})
    assert r.status_code in (200, 201), r.text

    await _login(api_client, MANAGER_EMAIL)
    r = await api_client.get("/api/v1/manager/users")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] == 2  # только клиенты, менеджер не в списке
    by_email = {item["email"]: item for item in body["data"]}

    assert by_email["one@example.by"]["orders_count"] == 1
    assert Decimal(by_email["one@example.by"]["avg_discount_percent"]) == Decimal("15")
    assert by_email["one@example.by"]["fixed_rate_currency"] is None

    assert by_email["two@example.by"]["orders_count"] == 0
    assert by_email["two@example.by"]["avg_discount_percent"] is None

    r = await api_client.get("/api/v1/manager/users", params={"q": "one@"})
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["email"] == "one@example.by"

    r = await api_client.get("/api/v1/manager/users", params={"q": "Ромашка"})
    assert r.json()["meta"]["total"] == 0


# ----------------------------------------------------------------- detail
async def test_get_user_detail_discounts(api_client, session_factory):
    sf = session_factory
    brand_a = await create_brand(sf, name="Alpha")
    await create_brand(sf, name="Beta")
    _, client = await _login_manager(api_client, sf)
    await set_discount(sf, user=client, brand=brand_a, percent=12.5)

    r = await api_client.get(f"/api/v1/manager/users/{client.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == str(client.id)
    assert body["user"]["fixed_rate"] is None
    by_name = {d["brand_name"]: d for d in body["discounts"]}
    assert set(by_name) == {"Alpha", "Beta"}
    assert Decimal(by_name["Alpha"]["percent"]) == Decimal("12.5")
    assert Decimal(by_name["Beta"]["percent"]) == 0

    assert (await api_client.get(f"/api/v1/manager/users/{uuid.uuid4()}")).status_code == 404


# ------------------------------------------------------------------ patch
async def test_patch_user_and_audit(api_client, session_factory):
    sf = session_factory
    manager, client = await _login_manager(api_client, sf)

    r = await api_client.patch(
        f"/api/v1/manager/users/{client.id}",
        json={"phone": "+375290000000", "is_active": False, "display_currency": "USD"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone"] == "+375290000000"
    assert body["is_active"] is False
    assert body["display_currency"] == "USD"

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "user.update")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].after["display_currency"] == "USD"
    assert entries[0].after["is_active"] is False
    assert entries[0].actor_id == manager.id


# -------------------------------------------------------- reset password
async def test_reset_password_revokes_sessions(api_client, session_factory):
    sf = session_factory
    manager, client = await _seed(sf)
    assert (await _login(api_client, CLIENT_EMAIL)).status_code == 200  # refresh-сессия
    assert (await _login(api_client, MANAGER_EMAIL)).status_code == 200  # куки менеджера

    r = await api_client.post(f"/api/v1/manager/users/{client.id}/reset-password")
    assert r.status_code == 200, r.text
    temp_password = r.json()["temp_password"]
    assert temp_password and temp_password != PASSWORD

    async with sf() as s:
        sessions = (await s.execute(
            select(SessionModel).where(SessionModel.user_id == client.id)
        )).scalars().all()
    assert sessions and all(sess.revoked for sess in sessions)

    assert (await _login(api_client, CLIENT_EMAIL, PASSWORD)).status_code == 401
    assert (await _login(api_client, CLIENT_EMAIL, temp_password)).status_code == 200

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "user.reset_password")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].after["sessions_revoked"] >= 1


# -------------------------------------------------------------- discounts
async def test_put_discounts_full_replace(api_client, session_factory):
    sf = session_factory
    brand_a = await create_brand(sf, name="Alpha")
    brand_b = await create_brand(sf, name="Beta")
    _, client = await _login_manager(api_client, sf)

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/discounts",
        json={"discounts": [
            {"brand_id": str(brand_a.id), "percent": "10"},
            {"brand_id": str(brand_b.id), "percent": "20"},
        ]},
    )
    assert r.status_code == 200, r.text
    by_id = {d["brand_id"]: d for d in r.json()}
    assert Decimal(by_id[str(brand_a.id)]["percent"]) == Decimal("10")
    assert Decimal(by_id[str(brand_b.id)]["percent"]) == Decimal("20")

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/discounts",
        json={"discounts": [{"brand_id": str(brand_a.id), "percent": "5"}]},
    )
    assert r.status_code == 200, r.text
    discounts = r.json()
    assert len(discounts) == 2  # все бренды, Beta вернулась к 0
    by_id = {d["brand_id"]: d for d in discounts}
    assert Decimal(by_id[str(brand_a.id)]["percent"]) == Decimal("5")
    assert Decimal(by_id[str(brand_b.id)]["percent"]) == 0

    async with sf() as s:
        rows = (await s.execute(
            select(UserBrand).where(UserBrand.user_id == client.id)
        )).scalars().all()
    assert [r.brand_id for r in rows] == [brand_a.id]  # Beta удалена (полная замена)

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog)
            .where(AuditLog.action == "user.discount.update")
            .order_by(AuditLog.created_at.desc())
        )).scalars().all()
    assert len(entries) == 2
    assert entries[0].before == {str(brand_a.id): "10.00", str(brand_b.id): "20.00"}
    assert entries[0].after == {str(brand_a.id): "5"}

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/discounts",
        json={"discounts": [{"brand_id": str(uuid.uuid4()), "percent": "5"}]},
    )
    assert r.status_code == 422


# ------------------------------------------------------------- fixed rate
async def test_fixed_rate_manual_set_and_reset(api_client, session_factory):
    sf = session_factory
    _, client = await _login_manager(api_client, sf)

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/fixed-rate",
        json={"currency_code": "USD", "rate": "3.1"},
    )
    assert r.status_code == 200, r.text
    fixed = r.json()["fixed_rate"]
    assert fixed["currency_code"] == "USD"
    assert Decimal(fixed["rate"]) == Decimal("3.1")
    assert fixed["source"] == "MANUAL"
    assert fixed["is_manual"] is True

    r = await api_client.get(f"/api/v1/manager/users/{client.id}")
    assert r.json()["user"]["fixed_rate"]["source"] == "MANUAL"

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "user.fixed_rate.set")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].after["currency_code"] == "USD"

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/fixed-rate", json={"reset": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["fixed_rate"] is None

    async with sf() as s:
        from app.models.user import User as UserModel

        db_user = await s.scalar(select(UserModel).where(UserModel.id == client.id))
    assert db_user.fixed_rate_id is None


async def test_fixed_rate_copies_nbrb_when_rate_omitted(api_client, session_factory):
    sf = session_factory
    await set_rate(sf, currency="EUR", rate=Decimal("3.5"), scale=1)
    _, client = await _login_manager(api_client, sf)

    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/fixed-rate",
        json={"currency_code": "EUR"},
    )
    assert r.status_code == 200, r.text
    fixed = r.json()["fixed_rate"]
    assert Decimal(fixed["rate"]) == Decimal("3.5")
    assert fixed["source"] == "MANUAL"
    assert fixed["scale"] == 1


async def test_fixed_rate_missing_nbrb_conflict(api_client, session_factory):
    sf = session_factory
    _, client = await _login_manager(api_client, sf)
    r = await api_client.put(
        f"/api/v1/manager/users/{client.id}/fixed-rate",
        json={"currency_code": "USD"},
    )
    assert r.status_code == 409


async def test_fixed_rate_requires_currency_or_reset(api_client, session_factory):
    sf = session_factory
    _, client = await _login_manager(api_client, sf)
    r = await api_client.put(f"/api/v1/manager/users/{client.id}/fixed-rate", json={})
    assert r.status_code == 422
