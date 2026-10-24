"""Серверное принуждение смены временного пароля (§11, §16 п.19).

Раньше флаг `must_change_password` только сообщался клиенту (`force_password_change`
в ответе логина), а редирект на /force-change-password делал фронт. С временным
паролем можно было полностью работать через API мимо страницы смены — достаточно
не открывать её в браузере.

Тесты проверяют серверный whitelist: /auth/me и /auth/change-password доступны,
обычные ресурсы закрыты 403.
"""
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User

EMAIL = "temp-password@example.com"
PASSWORD = "Passw0rd!"
NEW_PASSWORD = "N0vayaParol!"
CATALOG = "/api/v1/catalog/products"


async def _login(api_client, email: str = EMAIL, password: str = PASSWORD) -> str:
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return api_client.cookies.get("access_token")


async def _make_temp_user(session_factory) -> None:
    """Клиент с временным паролем — тот же сценарий, что у менеджера в UI.

    Вызывается из тела теста, а не фикстурой: pytest-asyncio выполняет фикстуры
    с loop_scope="session" один раз за прогон, а conftest чистит таблицы перед
    каждым тестом — пользователь просто исчезал бы к третьему тесту.
    """
    async with session_factory() as s:
        user = User(
            email=EMAIL,
            password_hash=hash_password(PASSWORD),
            full_name="Temp Password",
            role=UserRole.CLIENT,
            is_active=True,
            must_change_password=True,
        )
        s.add(user)
        await s.commit()
        # refresh обязателен: без него следующий запрос может не увидеть строку
        await s.refresh(user)


async def test_login_reports_force_password_change(api_client, session_factory):
    await _make_temp_user(session_factory)
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert r.json()["force_password_change"] is True


async def test_own_profile_is_reachable(api_client, session_factory):
    """Смена пароля невозможна, если нельзя даже посмотреть свой профиль."""
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    r = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text


async def test_change_password_endpoint_is_reachable(api_client, session_factory):
    """До сервиса смены пароля должно доходить, а не обрываться на 403."""
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code != 403, r.text


async def test_ordinary_endpoints_are_blocked(api_client, session_factory):
    """Ядро защиты: каталог недоступен, пока временный пароль не сменён."""
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    r = await api_client.get(CATALOG, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text
    assert "парол" in r.json()["detail"].lower()


async def test_cart_and_favorites_are_blocked(api_client, session_factory):
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    for path in ("/api/v1/cart", "/api/v1/favorites"):
        r = await api_client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, f"{path} → {r.status_code}"


async def test_logout_stays_available(api_client, session_factory):
    """Пользователь должен суметь выйти, даже если застрял на смене пароля."""
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    r = await api_client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code != 403, r.text


async def test_normal_user_is_not_affected(api_client, session_factory):
    """Без флага всё работает как раньше — защита не бьёт по обычным клиентам."""
    async with session_factory() as s:
        s.add(
            User(
                email="normal-client@example.com",
                password_hash=hash_password(PASSWORD),
                full_name="Normal",
                role=UserRole.CLIENT,
                is_active=True,
            )
        )
        await s.commit()
    token = await _login(api_client, "normal-client@example.com")
    r = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    r = await api_client.get(CATALOG, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text


async def test_password_change_clears_the_flag(api_client, session_factory):
    """После успешной смены пароля доступ возвращается.

    Смена пароля отзывает прочие сессии, поэтому логинимся заново.
    """
    await _make_temp_user(session_factory)
    token = await _login(api_client)
    r = await api_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    fresh = await _login(api_client, EMAIL, NEW_PASSWORD)
    r = await api_client.get(CATALOG, headers={"Authorization": f"Bearer {fresh}"})
    assert r.status_code == 200, r.text