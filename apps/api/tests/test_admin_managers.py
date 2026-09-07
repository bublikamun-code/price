"""Тесты администрирования: менеджеры (/api/v1/admin/managers). §6, §11 RBAC.

Контракт фронта (pages/manager/admin.vue): GET — плоский массив без конверта;
POST — 201 {user, temp_password}; PATCH — {is_active/full_name/phone}.
"""
import uuid

from sqlalchemy import select

from app.models.enums import UserRole
from app.models.system import AuditLog
from app.models.user import Session as SessionModel
from app.models.user import User
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
ADMIN_EMAIL = "admin@example.by"
MANAGER_EMAIL = "manager@example.by"
MANAGER2_EMAIL = "manager2@example.by"
CLIENT_EMAIL = "client@example.by"


async def _login(api_client, email, password=PASSWORD):
    return await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


async def _seed_admin(api_client, sf):
    await create_user(sf, email=ADMIN_EMAIL, role=UserRole.ADMIN, password=PASSWORD)
    r = await _login(api_client, ADMIN_EMAIL)
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------- RBAC
async def test_managers_require_admin_role(api_client, session_factory):
    sf = session_factory
    # Аноним → 401
    assert (await api_client.get("/api/v1/admin/managers")).status_code == 401
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL)
    assert (await api_client.get("/api/v1/admin/managers")).status_code == 403
    assert (
        await api_client.post(
            "/api/v1/admin/managers", json={"email": "m@x.by", "full_name": "M"}
        )
    ).status_code == 403
    # MANAGER тоже не пускать (require_admin, а не require_role)
    await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL)
    assert (await api_client.get("/api/v1/admin/managers")).status_code == 403


# ------------------------------------------------------------------- list
async def test_list_managers_bare_array(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)
    m1 = await create_user(sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    m2 = await create_user(sf, email=MANAGER2_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    r = await api_client.get("/api/v1/admin/managers")
    assert r.status_code == 200, r.text
    body = r.json()
    # Плоский массив — фронт кладёт ответ прямо в таблицу (без unwrapData)
    assert isinstance(body, list)
    emails = {item["email"] for item in body}
    assert emails == {MANAGER_EMAIL, MANAGER2_EMAIL}
    item = next(i for i in body if i["id"] == str(m1.id))
    assert item["email"] == MANAGER_EMAIL
    assert item["full_name"] == m1.full_name
    assert item["is_active"] is True
    assert item["phone"] is None
    assert item["created_at"]
    assert str(m2.id) in {i["id"] for i in body}


# ----------------------------------------------------------------- create
async def test_create_manager_with_temp_password(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)

    r = await api_client.post(
        "/api/v1/admin/managers",
        json={"email": "New.Manager@Example.by", "full_name": "Иванов Иван", "phone": "+375291234567"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    temp_password = body["temp_password"]
    assert temp_password
    assert body["user"]["email"] == "new.manager@example.by"
    assert body["user"]["full_name"] == "Иванов Иван"
    assert body["user"]["phone"] == "+375291234567"
    assert body["user"]["is_active"] is True
    assert body["user"]["created_at"]

    # temp-пароль работает + флаг обязательной смены (§16 п.19)
    login = await _login(api_client, "new.manager@example.by", temp_password)
    assert login.status_code == 200, login.text
    assert login.json().get("force_password_change") is True

    async with sf() as s:
        user = (await s.execute(
            select(User).where(User.email == "new.manager@example.by")
        )).scalar_one()
        assert user.role == UserRole.MANAGER
        assert user.must_change_password is True

        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "manager.create")
        )).scalars().all()
    assert len(entries) == 1
    assert entries[0].after["email"] == "new.manager@example.by"


async def test_create_manager_duplicate_email_409(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)
    payload = {"email": "dup@example.by", "full_name": "Dup"}
    assert (await api_client.post("/api/v1/admin/managers", json=payload)).status_code == 201
    # Тот же email в другом регистре — тоже конфликт (CITEXT)
    r = await api_client.post(
        "/api/v1/admin/managers", json={"email": "DUP@example.by", "full_name": "Dup2"}
    )
    assert r.status_code == 409, r.text


# ------------------------------------------------------------------ patch
async def test_patch_block_revokes_sessions_and_unblock(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)
    manager = await create_user(
        sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    # Сессия менеджера (refresh-куки + access)
    login = await _login(api_client, MANAGER_EMAIL)
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    # Возвращаем админскую сессию: _login перезаписал куки на менеджерские
    await _login(api_client, ADMIN_EMAIL)

    r = await api_client.patch(
        f"/api/v1/admin/managers/{manager.id}", json={"is_active": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    # Активные сессии отозваны немедленно (текст подтверждения на фронта)
    async with sf() as s:
        sessions = (await s.execute(
            select(SessionModel).where(SessionModel.user_id == manager.id)
        )).scalars().all()
    assert sessions and all(sess.revoked for sess in sessions)

    # Старый access-токен больше не работает
    r = await api_client.get(
        "/api/v1/admin/managers",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r.status_code == 401

    # Разблокировка
    r = await api_client.patch(
        f"/api/v1/admin/managers/{manager.id}", json={"is_active": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    async with sf() as s:
        entries = (await s.execute(
            select(AuditLog).where(AuditLog.action == "manager.update")
        )).scalars().all()
    assert len(entries) == 2
    assert entries[0].actor_id is not None
    assert entries[0].after["is_active"] is False


async def test_patch_full_name_and_phone(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)
    manager = await create_user(
        sf, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    assert manager.full_name != "Новое Имя"
    r = await api_client.patch(
        f"/api/v1/admin/managers/{manager.id}",
        json={"full_name": "Новое Имя", "phone": "+375290000000"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Новое Имя"
    assert body["phone"] == "+375290000000"


async def test_patch_unknown_or_non_manager_404(api_client, session_factory):
    sf = session_factory
    await _seed_admin(api_client, sf)
    client = await create_user(sf, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    # Неизвестный id
    r = await api_client.patch(
        f"/api/v1/admin/managers/{uuid.uuid4()}", json={"is_active": False}
    )
    assert r.status_code == 404, r.text
    # Клиент через admin/managers недоступен (не менеджер)
    r = await api_client.patch(
        f"/api/v1/admin/managers/{client.id}", json={"is_active": False}
    )
    assert r.status_code == 404, r.text
