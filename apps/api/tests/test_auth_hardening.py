"""Усиление аутентификации: M8 (aud/iss в JWT), M9 (одноразовый 2FA-ticket и
одноразовый TOTP-код), L9 (режим cookie «Запомнить меня»).

Аудит 2026-11-10, находки M8, M9, L9.

Покрытие:
  - M8: в access-токене есть aud/iss; чужой aud, чужой iss, токен без aud и
    токен без iss → 401; валидный токен → 200.
  - M9: 2FA-ticket одноразовый (повтор → 401); неверный код не «сжигает»
    ticket; TOTP-код не переиспользуется в том же окне; следующий шаг окна
    принимается; ticket с чужим jti / несуществующим → 401; отключение 2FA
    не «сжигает» шаг (код остаётся пригодным для входа).
  - L9: remember=true → cookie с Max-Age; remember=false → сессионные cookie
    (без Max-Age/Expires); режим переживает ротацию refresh; claim `remember`
    в 2FA-ticket имеет приоритет над телом запроса.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from sqlalchemy import select

from app.core.config import settings
from app.models.enums import UserRole
from app.models.user import TwoFactorChallenge
from app.models.user import User
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
EMAIL = "manager@example.by"
TOTP_SECRET = pyotp.random_base32()


# ---------- helpers ----------
async def _manager(session_factory, *, totp: bool = True):
    user = await create_user(
        session_factory, email=EMAIL, role=UserRole.MANAGER, password=PASSWORD
    )
    if totp:
        async with session_factory() as s:
            row = await s.get(User, user.id)
            row.totp_secret = TOTP_SECRET
            await s.commit()
    return user


async def _login(api_client, **overrides):
    payload = {"email": EMAIL, "password": PASSWORD}
    payload.update(overrides)
    return await api_client.post("/api/v1/auth/login", json=payload)


async def _ticket(api_client, **overrides) -> str:
    """Логин с включённой 2FA → возвращает ticket второго шага."""
    r = await _login(api_client, **overrides)
    assert r.status_code == 200, r.text
    return r.json()["data"]["ticket"]


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_verify_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )


def _make_access_token(user_id, **overrides) -> str:
    """Access-токен с произвольными claim'ами aud/iss (минуя _create_token)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    for key in overrides.pop("_drop", ()):
        payload.pop(key, None)
    payload.update(overrides)
    return jwt.encode(
        payload, settings.jwt_signing_key, algorithm=settings.jwt_algorithm
    )


def _cookie_headers(response, name: str) -> list[str]:
    return [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


def _has_max_age(header: str) -> bool:
    return "max-age" in header.lower()


# =========================================================
# M8 — обязательные aud/iss в JWT
# =========================================================
async def test_access_token_contains_aud_and_iss(api_client, session_factory):
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": "plain@example.by", "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    payload = _decode(r.json()["access_token"])
    assert payload["aud"] == settings.jwt_audience
    assert payload["iss"] == settings.jwt_issuer
    assert payload["sub"] == str(user.id)


async def test_token_with_foreign_audience_is_rejected(api_client, session_factory):
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    token = _make_access_token(user.id, aud="another-environment")
    r = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_with_foreign_issuer_is_rejected(api_client, session_factory):
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    token = _make_access_token(user.id, iss="another-environment")
    r = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_without_audience_is_rejected(api_client, session_factory):
    """Старый токен без aud/iss больше не принимается (ожидаемое следствие M8)."""
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    token = _make_access_token(user.id, _drop=("aud",))
    r = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_without_issuer_is_rejected(api_client, session_factory):
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    token = _make_access_token(user.id, _drop=("iss",))
    r = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_valid_token_is_accepted(api_client, session_factory):
    user = await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    token = _make_access_token(user.id)
    r = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "plain@example.by"


# =========================================================
# M9 — 2FA-ticket одноразовый
# =========================================================
async def test_2fa_ticket_is_single_use(api_client, session_factory):
    await _manager(session_factory)
    ticket = await _ticket(api_client)
    code = pyotp.TOTP(TOTP_SECRET).now()

    first = await api_client.post(
        "/api/v1/auth/2fa/verify", json={"ticket": ticket, "code": code}
    )
    assert first.status_code == 200, first.text

    # Тот же ticket второй раз → 401 (раньше выдавал ещё одну сессию).
    second = await api_client.post(
        "/api/v1/auth/2fa/verify", json={"ticket": ticket, "code": code}
    )
    assert second.status_code == 401


async def test_2fa_ticket_is_marked_used_in_db(api_client, session_factory):
    await _manager(session_factory)
    ticket = await _ticket(api_client)
    jti = _decode(ticket)["jti"]
    code = pyotp.TOTP(TOTP_SECRET).now()
    r = await api_client.post(
        "/api/v1/auth/2fa/verify", json={"ticket": ticket, "code": code}
    )
    assert r.status_code == 200, r.text

    async with session_factory() as s:
        row = await s.scalar(
            select(TwoFactorChallenge).where(TwoFactorChallenge.jti == jti)
        )
        assert row is not None
        assert row.used_at is not None


async def test_wrong_code_does_not_burn_ticket(api_client, session_factory):
    """Неверный код откатывает транзакцию: ticket остаётся пригодным."""
    await _manager(session_factory)
    ticket = await _ticket(api_client)

    wrong = await api_client.post(
        "/api/v1/auth/2fa/verify", json={"ticket": ticket, "code": "000000"}
    )
    assert wrong.status_code == 401

    right = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": ticket, "code": pyotp.TOTP(TOTP_SECRET).now()},
    )
    assert right.status_code == 200, right.text


async def test_ticket_with_unknown_jti_is_rejected(api_client, session_factory):
    """Подделанный jti (запись в БД отсутствует) → 401."""
    await _manager(session_factory)
    ticket = await _ticket(api_client)
    payload = _decode(ticket)
    payload["jti"] = "0" * 32
    forged = jwt.encode(
        payload, settings.jwt_signing_key, algorithm=settings.jwt_algorithm
    )

    r = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": forged, "code": pyotp.TOTP(TOTP_SECRET).now()},
    )
    assert r.status_code == 401


async def test_ticket_of_another_user_is_rejected(api_client, session_factory):
    await _manager(session_factory)
    other = await create_user(
        session_factory, email="other@example.by", role=UserRole.MANAGER
    )
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": str(other.id),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "type": "2fa",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": "f" * 32,
            "remember": True,
        },
        settings.jwt_signing_key,
        algorithm=settings.jwt_algorithm,
    )
    r = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": forged, "code": pyotp.TOTP(TOTP_SECRET).now()},
    )
    assert r.status_code == 401


# =========================================================
# M9 — TOTP-код не переиспользуется
# =========================================================
async def test_totp_code_cannot_be_reused_in_same_window(api_client, session_factory):
    """Код, уже принятый в этом окне, второй раз не принимается."""
    await _manager(session_factory)
    code = pyotp.TOTP(TOTP_SECRET).now()

    first = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": await _ticket(api_client), "code": code},
    )
    assert first.status_code == 200, first.text

    # Новый login → новый ticket, но код тот же и в том же окне.
    second = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": await _ticket(api_client), "code": code},
    )
    assert second.status_code == 401


async def test_totp_next_window_code_is_accepted(api_client, session_factory):
    """Следующий шаг окна валиден: запрещён только повтор уже использованного."""
    await _manager(session_factory)
    totp = pyotp.TOTP(TOTP_SECRET)
    next_step = totp.at(datetime.now(timezone.utc) + timedelta(seconds=totp.interval))

    r = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": await _ticket(api_client), "code": next_step},
    )
    assert r.status_code == 200, r.text


async def test_disable_2fa_accepts_code_already_used_for_login(api_client, session_factory):
    """Проверка кода при отключении 2FA не «сжигает» шаг и не отвергает код,
    которым только что вошли: отключение — чистая проверка."""
    user = await _manager(session_factory)
    code = pyotp.TOTP(TOTP_SECRET).now()

    logged_in = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": await _ticket(api_client), "code": code},
    )
    assert logged_in.status_code == 200, logged_in.text

    disabled = await api_client.post("/api/v1/auth/2fa/disable", json={"code": code})
    assert disabled.status_code == 204, disabled.text

    async with session_factory() as s:
        row = await s.get(User, user.id)
        assert row.totp_secret is None
        assert row.totp_last_step is None

    # 2FA выключена → вход сразу даёт токены (без второго шага).
    r = await _login(api_client)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


# =========================================================
# L9 — «Запомнить меня»
# =========================================================
async def test_login_remember_true_sets_persistent_cookies(api_client, session_factory):
    await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain@example.by", "password": PASSWORD, "remember": True},
    )
    assert r.status_code == 200, r.text
    for name in ("access_token", "refresh_token", "csrf_token"):
        header = _cookie_headers(r, name)[0]
        assert _has_max_age(header), header


async def test_login_remember_false_sets_session_cookies(api_client, session_factory):
    await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain@example.by", "password": PASSWORD, "remember": False},
    )
    assert r.status_code == 200, r.text
    for name in ("access_token", "refresh_token", "csrf_token"):
        header = _cookie_headers(r, name)[0]
        assert not _has_max_age(header), header
        assert "expires" not in header.lower(), header


async def test_login_without_remember_field_keeps_legacy_behaviour(api_client, session_factory):
    """Поле remember опционально: без него — прежнее поведение (постоянные cookie)."""
    await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": "plain@example.by", "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert _has_max_age(_cookie_headers(r, "refresh_token")[0])


async def test_refresh_keeps_session_cookie_mode(api_client, session_factory):
    """Ротация refresh-токена не меняет режим cookie."""
    await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain@example.by", "password": PASSWORD, "remember": False},
    )
    assert r.status_code == 200, r.text

    refreshed = await api_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert not _has_max_age(_cookie_headers(refreshed, "refresh_token")[0])


async def test_refresh_keeps_persistent_cookie_mode(api_client, session_factory):
    await create_user(session_factory, email="plain@example.by", role=UserRole.CLIENT)
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain@example.by", "password": PASSWORD, "remember": True},
    )
    assert r.status_code == 200, r.text

    refreshed = await api_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert _has_max_age(_cookie_headers(refreshed, "refresh_token")[0])


async def test_2fa_ticket_carries_remember_claim(api_client, session_factory):
    await _manager(session_factory)
    ticket = await _ticket(api_client, remember=False)
    assert _decode(ticket)["remember"] is False


async def test_2fa_verify_uses_remember_claim_from_ticket(api_client, session_factory):
    """Claim ticket'а приоритетнее тела запроса: remember=false из login."""
    await _manager(session_factory)
    ticket = await _ticket(api_client, remember=False)
    r = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={
            "ticket": ticket,
            "code": pyotp.TOTP(TOTP_SECRET).now(),
            "remember": True,
        },
    )
    assert r.status_code == 200, r.text
    assert not _has_max_age(_cookie_headers(r, "refresh_token")[0])


async def test_2fa_verify_falls_back_to_body_remember(api_client, session_factory):
    """Если claim'а в ticket нет — берётся поле тела запроса."""
    await _manager(session_factory)
    ticket = await _ticket(api_client, remember=True)
    # Убираем claim из ticket'а (fallback-сценарий для билдов без claim'а).
    payload = _decode(ticket)
    payload.pop("remember")
    stripped = jwt.encode(
        payload, settings.jwt_signing_key, algorithm=settings.jwt_algorithm
    )

    r = await api_client.post(
        "/api/v1/auth/2fa/verify",
        json={"ticket": stripped, "code": pyotp.TOTP(TOTP_SECRET).now(), "remember": False},
    )
    assert r.status_code == 200, r.text
    assert not _has_max_age(_cookie_headers(r, "refresh_token")[0])


# ---------- Secure-флаг кук и схема запроса ----------
# Публичная точка — https (Tailscale Funnel): куки должны быть Secure.
# Внутренний стенд по http: Secure-куку браузер не отправит, вход был бы
# невозможен — поэтому по http флаг снимается (в боевом проде nginx
# перенаправляет http → https, §19, и ослабления там нет).
def test_secure_flag_follows_request_scheme(monkeypatch):
    """Схема берётся из X-Forwarded-Proto: uvicorn 0.30 не переписывает scheme."""
    from types import SimpleNamespace

    from app.api.v1.auth import _secure_cookie

    monkeypatch.setattr(settings, "cookie_secure", True)

    class _Запрос:
        def __init__(self, scheme: str, forwarded: str | None = None) -> None:
            self.url = SimpleNamespace(scheme=scheme)
            self.headers = {} if forwarded is None else {"x-forwarded-proto": forwarded}

    # Внешний прокси (Funnel) сообщил https — кука Secure.
    assert _secure_cookie(_Запрос("http", forwarded="https")) is True
    # Внутренний стенд по http — Secure-куку браузер не отправит.
    assert _secure_cookie(_Запрос("http", forwarded="http")) is False
    assert _secure_cookie(_Запрос("http")) is False
    assert _secure_cookie(_Запрос("https")) is True
    # Схему узнать нечем — держим строгую политику.
    assert _secure_cookie(None) is True

    monkeypatch.setattr(settings, "cookie_secure", False)
    assert _secure_cookie(_Запрос("http", forwarded="https")) is False


async def test_login_over_http_has_no_secure_flag(api_client, session_factory, monkeypatch):
    """По http cookie без Secure — иначе браузер её не отправит."""
    monkeypatch.setattr(settings, "cookie_secure", True)
    # Без 2FA: иначе логин вернёт ticket, а не токены, и cookie не выставятся.
    await _manager(session_factory, totp=False)
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD, "remember": True},
    )
    assert r.status_code == 200, r.text
    assert "secure" not in _cookie_headers(r, "access_token")[0].lower()
