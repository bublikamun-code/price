"""Интеграционные тесты аутентификации и RBAC. См. ARCHITECTURE_PLAN.md §6, §11.

Покрытие:
  - login: успех, неверный пароль, неактивный пользователь, case-insensitive email
  - /me: с токеном, без токена (401), с кривым токеном (401)
  - PATCH /me: display_currency (нормализация/422), дайджест цен (§20.4), дедупликация источников, пустое тело (422), без токена (401)
  - refresh: rotation, grace-окно (аудит P0-1: старый токен в пределах окна → 200, после → 401)
  - change-password: смена временного пароля, снятие must_change_password, инвалидация других сессий
  - CSRF double-submit: в т.ч. для cookie-аутентификации auth_token (аудит 2026-09-06)
  - logout: отзыв сессии, /me после logout (401)
  - cookie Secure-флаг из COOKIE_SECURE (§16 п.30): dev false / prod true
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
    assert "csrf_token" in r.cookies
    csrf_header = next(h for h in r.headers.get_list("set-cookie") if h.startswith("csrf_token="))
    assert "HttpOnly" not in csrf_header
    assert "SameSite=lax" in csrf_header


async def test_login_cookies_not_secure_by_default(api_client, session_factory, monkeypatch):
    """Dev (COOKIE_SECURE=false, §16 п.30): куки без Secure, остальное как раньше."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "cookie_secure", False)  # детерминизм вне .env
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    r = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    assert r.status_code == 200, r.text
    set_cookies = r.headers.get_list("set-cookie")
    names = {h.split("=", 1)[0] for h in set_cookies}
    assert {"access_token", "refresh_token", "csrf_token"} <= names
    assert all("secure" not in h.lower() for h in set_cookies)


async def test_login_cookies_secure_when_configured(api_client, session_factory, monkeypatch):
    """§16 п.30: при COOKIE_SECURE=true все три куки получают флаг Secure."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "cookie_secure", True)
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    r = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    assert r.status_code == 200, r.text
    set_cookies = r.headers.get_list("set-cookie")
    names = {h.split("=", 1)[0] for h in set_cookies}
    assert {"access_token", "refresh_token", "csrf_token"} <= names
    assert all("secure" in h.lower() for h in set_cookies)


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
# PATCH /ME (профиль: display_currency, дайджест цен — §6, §20.4)
# =========================================================
async def test_me_returns_digest_fields(api_client, session_factory):
    """GET /me отдаёт настройки дайджеста: выключен, все 3 источника по умолчанию."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price_digest_enabled"] is False
    assert body["price_digest_sources"] == ["cart", "favorite", "orders"]


async def test_patch_me_updates_digest(api_client, session_factory):
    """PATCH настроек дайджеста: ответ отражает изменения и они зафиксированы в БД."""
    from app.models.user import User

    user = await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.patch(
        "/api/v1/auth/me",
        json={"price_digest_enabled": True, "price_digest_sources": ["cart", "orders"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price_digest_enabled"] is True
    assert body["price_digest_sources"] == ["cart", "orders"]

    async with session_factory() as s:
        db_user = await s.get(User, user.id)
        assert db_user.price_digest_enabled is True
        assert db_user.price_digest_sources == ["cart", "orders"]


async def test_patch_me_display_currency_manager_can_change(api_client, session_factory):
    """MANAGER может менять валюту отображения как раньше ('usd' → 'USD')."""
    await create_user(session_factory, email=MANAGER_EMAIL, role=UserRole.MANAGER, password=PASSWORD)
    await _login(api_client, MANAGER_EMAIL, PASSWORD)
    r = await api_client.patch("/api/v1/auth/me", json={"display_currency": " usd "})
    assert r.status_code == 200, r.text
    assert r.json()["display_currency"] == "USD"


async def test_patch_me_display_currency_invalid(api_client, session_factory):
    """display_currency обязана быть ровно 3 латинскими заглавными (после нормализации)."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    for bad in ("us", "USDD", "ЁUR", ""):
        r = await api_client.patch("/api/v1/auth/me", json={"display_currency": bad})
        assert r.status_code == 422, f"{bad!r}: {r.status_code} {r.text}"


async def test_patch_me_invalid_source(api_client, session_factory):
    """Источники дайджеста — только 'cart' | 'favorite' | 'orders'."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.patch(
        "/api/v1/auth/me", json={"price_digest_sources": ["wishlist"]}
    )
    assert r.status_code == 422


async def test_patch_me_dedup_sources(api_client, session_factory):
    """Дубликаты источников дедуплицируются (порядок сохраняется)."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.patch(
        "/api/v1/auth/me", json={"price_digest_sources": ["cart", "cart", "orders"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["price_digest_sources"] == ["cart", "orders"]


async def test_patch_me_empty_body(api_client, session_factory):
    """Пустое тело / все поля null → 422 «нечего обновлять»."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.patch("/api/v1/auth/me", json={})
    assert r.status_code == 422


async def test_patch_me_unauthorized(api_client):
    """Без авторизации PATCH /me → 401."""
    r = await api_client.patch("/api/v1/auth/me", json={"price_digest_enabled": True})
    assert r.status_code == 401


# =========================================================
# CSRF double-submit
# =========================================================
async def test_csrf_cookie_request_success_and_safe_get(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    assert (await api_client.get("/api/v1/auth/me")).status_code == 200
    r = await api_client.patch("/api/v1/auth/me", json={"display_currency": "USD"})
    assert r.status_code == 200, r.text


async def test_csrf_missing_and_wrong_token_forbidden(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    original_request = api_client.request

    async def raw_request(method, url, **kwargs):
        return await original_request(method, url, **kwargs)

    # Обходим автоподстановку CSRF из тестовой фикстуры.
    api_client.request = raw_request
    api_client.cookies.delete("csrf_token")
    missing = await api_client.patch("/api/v1/auth/me", json={"display_currency": "USD"})
    assert missing.status_code == 403

    api_client.cookies.set("csrf_token", "cookie-token")
    wrong = await api_client.patch(
        "/api/v1/auth/me",
        json={"display_currency": "USD"},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert wrong.status_code == 403


async def test_bearer_only_mutation_does_not_require_csrf(api_client, session_factory):
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    login = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    access = login.json()["access_token"]
    api_client.cookies.clear()
    r = await api_client.patch(
        "/api/v1/auth/me",
        json={"display_currency": "USD"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200, r.text


async def test_login_with_stale_cookies_without_csrf_passes(api_client, session_factory):
    """§16 п.21: login освобождён от CSRF — остаточные токен-куки без csrf-куки
    не ломают перезайти; успешный ответ перезаписывает все три куки."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    api_client.cookies.set("access_token", "stale-access")
    api_client.cookies.set("refresh_token", "stale-refresh")
    # csrf-куки нет, заголовка нет — без exemption был бы 403
    r = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    assert r.status_code == 200, r.text
    assert "access_token" in r.cookies
    assert "refresh_token" in r.cookies
    assert "csrf_token" in r.cookies


async def test_login_wrong_password_clears_stale_cookies(api_client, session_factory):
    """§16 п.21: неуспешный логин (401) чистит остаточные access/refresh/csrf куки."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    api_client.cookies.set("access_token", "stale-access")
    api_client.cookies.set("refresh_token", "stale-refresh")
    r = await _login(api_client, CLIENT_EMAIL, "wrong")
    assert r.status_code == 401
    set_cookies = r.headers.get_list("set-cookie")
    names = {h.split("=", 1)[0] for h in set_cookies}
    assert {"access_token", "refresh_token", "csrf_token"} <= names
    assert all("max-age=0" in h.lower() for h in set_cookies)  # удаление, а не установка


async def test_refresh_and_logout_still_require_csrf(api_client, session_factory):
    """Exemption только для login (§16 п.21): refresh/logout с токен-куками
    без совпадающего csrf → 403."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    api_client.cookies.set("access_token", "stale-access")
    api_client.cookies.set("refresh_token", "stale-refresh")
    # csrf-куки нет → автоподстановка заголовка из фикстуры не сработает
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 403
    assert (await api_client.post("/api/v1/auth/logout")).status_code == 403


async def test_csrf_required_for_auth_token_cookie(api_client, session_factory):
    """Аудит 2026-09-06: аутентификация не-httpOnly кукой auth_token (так хранит
    токен фронт) тоже требует CSRF double-submit на мутациях."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    login = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    access = login.json()["access_token"]

    # Имитация фронта: httpOnly-куки убраны, остаётся только auth_token;
    # автоподстановку CSRF-заголовка из тестовой фикстуры отключаем.
    original_request = api_client.request

    async def raw_request(method, url, **kwargs):
        return await original_request(method, url, **kwargs)

    api_client.request = raw_request
    api_client.cookies.clear()
    api_client.cookies.set("auth_token", access)

    # без csrf-куки и заголовка → 403 (раньше мутация проходила без CSRF)
    missing = await api_client.patch("/api/v1/auth/me", json={"display_currency": "USD"})
    assert missing.status_code == 403

    # согласованная пара cookie+header → 200
    api_client.cookies.set("csrf_token", "test-csrf")
    ok = await api_client.patch(
        "/api/v1/auth/me",
        json={"display_currency": "USD"},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert ok.status_code == 200, ok.text


# =========================================================
# REFRESH (rotation + grace-окно)
# =========================================================
async def test_refresh_rotation_and_old_invalid(api_client, session_factory, monkeypatch):
    """Ротация: старый refresh в пределах grace-окна (аудит P0-1) принимается
    и «догоняет» цепочку до актуальной сессии; после окна — 401."""
    from app.core.config import settings

    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)

    r1 = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    refresh_old = r1.cookies["refresh_token"]

    r2 = await api_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text
    refresh_new = r2.cookies["refresh_token"]
    assert refresh_new != refresh_old  # rotation: новый токен

    # Старый refresh сразу после ротации: grace → 200, выдан очередной токен
    api_client.cookies.set("refresh_token", refresh_old)
    r3 = await api_client.post("/api/v1/auth/refresh")
    assert r3.status_code == 200, r3.text
    refresh_grace = r3.cookies["refresh_token"]
    assert refresh_grace not in (refresh_old, refresh_new)

    # Окно истекло (refresh_grace_seconds=0): тот же старый токен → 401
    # (reuse-detection сохранён)
    monkeypatch.setattr(settings, "refresh_grace_seconds", 0)
    r4 = await api_client.post("/api/v1/auth/refresh")
    assert r4.status_code == 401

    # Последний выданный токен — валиден
    api_client.cookies.set("refresh_token", refresh_grace)
    r5 = await api_client.post("/api/v1/auth/refresh")
    assert r5.status_code == 200


async def test_refresh_grace_chain_multiple_tabs(api_client, session_factory):
    """Две «вкладки» соревнуются одним старым токеном: обе получают 200 и
    валидные пары; цепочка ротаций не рвётся (аудит P0-1, гонка POST /refresh)."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    r1 = await _login(api_client, CLIENT_EMAIL, PASSWORD)
    old = r1.cookies["refresh_token"]

    r2 = await api_client.post("/api/v1/auth/refresh")  # вкладка A
    assert r2.status_code == 200
    token_a = r2.cookies["refresh_token"]

    api_client.cookies.set("refresh_token", old)
    r3 = await api_client.post("/api/v1/auth/refresh")  # вкладка B опоздала — grace
    assert r3.status_code == 200, r3.text
    token_b = r3.cookies["refresh_token"]

    # Оба новых токена валидны (каждый был «актуальным» на момент выдачи)
    api_client.cookies.set("refresh_token", token_a)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 200
    api_client.cookies.set("refresh_token", token_b)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 200


async def test_refresh_from_cookie(api_client, session_factory):
    """Без тела — refresh берётся из httpOnly cookie."""
    await create_user(session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password=PASSWORD)
    await _login(api_client, CLIENT_EMAIL, PASSWORD)
    r = await api_client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


# =========================================================
# CHANGE-PASSWORD (смена временного пароля, §16 п.19, /force-change-password)
# =========================================================
async def _set_must_change(session_factory, user_id, value: bool = True) -> None:
    from app.models.user import User

    async with session_factory() as s:
        u = await s.get(User, user_id)
        u.must_change_password = value
        await s.commit()


async def test_change_password_success(api_client, session_factory):
    """Смена временного пароля: флаг снят (БД и /me), другие сессии отозваны,
    текущая выживает, старый пароль не работает, новый — работает."""
    from datetime import datetime, timedelta, timezone

    from app.models.user import Session as SessionModel
    from app.models.user import User
    from app.services.auth import _hash_token

    user = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password="TempPass!23"
    )
    await _set_must_change(session_factory, user.id)

    # «Второе устройство»: отдельная сессия того же пользователя — её refresh-токен
    other_plain = "other-device-refresh-token"
    async with session_factory() as s:
        s.add(SessionModel(
            user_id=user.id,
            refresh_token_hash=_hash_token(other_plain),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            revoked=False,
        ))
        await s.commit()

    await _login(api_client, CLIENT_EMAIL, "TempPass!23")
    current_refresh = api_client.cookies["refresh_token"]
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "TempPass!23", "new_password": "NewPass!234"},
    )
    assert r.status_code == 200, r.text

    # флаг снят в БД и в /me
    async with session_factory() as s:
        u = await s.get(User, user.id)
        assert u.must_change_password is False
    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["force_password_change"] is False

    # другая сессия отозвана (rotated_at NULL → grace не применяется) → 401
    api_client.cookies.set("refresh_token", other_plain)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 401

    # текущая сессия выжила → refresh по её куке работает
    api_client.cookies.set("refresh_token", current_refresh)
    assert (await api_client.post("/api/v1/auth/refresh")).status_code == 200

    # старый пароль больше не работает, новый работает
    assert (await _login(api_client, CLIENT_EMAIL, "TempPass!23")).status_code == 401
    assert (await _login(api_client, CLIENT_EMAIL, "NewPass!234")).status_code == 200


async def test_change_password_wrong_current(api_client, session_factory):
    """Неверный текущий пароль → 400, пароль и флаг не менялись."""
    from app.models.user import User

    user = await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password="TempPass!23"
    )
    await _set_must_change(session_factory, user.id)
    await _login(api_client, CLIENT_EMAIL, "TempPass!23")
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WrongPass!1", "new_password": "NewPass!234"},
    )
    assert r.status_code == 400
    async with session_factory() as s:
        u = await s.get(User, user.id)
        assert u.must_change_password is True


async def test_change_password_short_new_password(api_client, session_factory):
    """Аудит D: новый пароль короче 8 символов → 422."""
    await create_user(
        session_factory, email=CLIENT_EMAIL, role=UserRole.CLIENT, password="TempPass!23"
    )
    await _login(api_client, CLIENT_EMAIL, "TempPass!23")
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "TempPass!23", "new_password": "short"},
    )
    assert r.status_code == 422


async def test_change_password_unauthorized(api_client):
    """Без авторизации → 401."""
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "x", "new_password": "NewPass!234"},
    )
    assert r.status_code == 401


async def test_reset_password_min_length_enforced(api_client, session_factory):
    """Аудит D: POST /auth/reset-password отклоняет пароль короче 8 символов (422)."""
    r = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "any-token", "new_password": "short"},
    )
    assert r.status_code == 422


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

    # refresh после logout не работает (CSRF-cookie+header нужны, чтобы дойти
    # до проверки сессии, а не получить 403 от CSRF-middleware)
    api_client.cookies.set("refresh_token", refresh)
    api_client.cookies.set("csrf_token", "test-csrf")
    r3 = await api_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "test-csrf"})
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
