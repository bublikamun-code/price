"""Тесты входа из Telegram Mini App (POST /api/m/v1/auth/telegram, §16 п.27).

initData подписывается по официальному алгоритму Telegram:
  secret = HMAC("WebAppData", bot_token)
  hash   = HMAC(secret, data_check_string)  # отсортированные k=v через \n
"""
import hashlib
import hmac
import json
import time
import urllib.parse

import pytest

from app.core.config import settings
from app.models.enums import UserRole
from tests.conftest import create_user

PASSWORD = "Passw0rd!"
BOT_TOKEN = "12345:unittest-token"
TG_ID = 777001


def _sign(init: dict, token: str) -> str:
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={init[k]}" for k in sorted(init))
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def _make_init_data(tg_id: int, token: str = BOT_TOKEN, age: int = 0) -> str:
    # подпись ставится по ЗНАЧЕНИЯМ КАК ОТПРАВЛЕНЫ (urlencoded), как в Telegram
    init = {
        "auth_date": str(int(time.time()) - age),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": urllib.parse.quote(
            json.dumps({"id": tg_id, "first_name": "Тест"}, separators=(",", ":"))
        ),
    }
    init["hash"] = _sign(init, token)
    return "&".join(f"{k}={v}" for k, v in init.items())


@pytest.fixture(autouse=True)
def _bot_token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)


class _FakeRedis:
    """Мини-стаб redis для link-кодов (set/get/getdel/delete/incr/expire)."""

    def __init__(self):
        self.data: dict = {}

    def set(self, key, value, ex=None, **kw):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)

    def getdel(self, key):
        return self.data.pop(key, None)

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    def expire(self, key, seconds):
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    from app.services import telegram_auth as ta

    fake = _FakeRedis()
    monkeypatch.setattr(ta, "_get_redis", lambda: fake)
    return fake


# ------------------------------------------------------------------ success
async def _user_id(session_factory, email: str):
    from sqlalchemy import select

    from app.models.user import User

    async with session_factory() as s:
        return (
            await s.execute(select(User.id).where(User.email == email))
        ).scalar_one()


async def test_miniapp_login_with_link_code_binds_and_200(api_client, session_factory, fake_redis):
    from app.services.telegram_auth import generate_link_code

    await create_user(
        session_factory, email="mini@x.by", role=UserRole.CLIENT, password=PASSWORD
    )
    user_id = await _user_id(session_factory, "mini@x.by")
    code = generate_link_code(user_id)
    # 8 цифр, а не 6: перебор шестизначного кода укладывается в TTL
    assert len(code["code"]) == 8 and code["code"].isdigit()

    r = await api_client.post(
        "/api/m/v1/auth/telegram",
        json={"init_data": _make_init_data(TG_ID), "link_code": code["code"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"

    # привязка записана: повторный вход без кода — тоже 200
    r2 = await api_client.post(
        "/api/m/v1/auth/telegram", json={"init_data": _make_init_data(TG_ID), "link_code": ""}
    )
    assert r2.status_code == 200, r2.text


# ------------------------------------------------------------------ failures
async def test_miniapp_unknown_telegram_401(api_client):
    r = await api_client.post(
        "/api/m/v1/auth/telegram", json={"init_data": _make_init_data(424242), "link_code": ""}
    )
    assert r.status_code == 401
    assert "не привязан" in r.json()["detail"]


async def test_miniapp_tampered_signature_401(api_client):
    init = {
        "auth_date": str(int(time.time())),
        "user": urllib.parse.quote(json.dumps({"id": 424242}, separators=(",", ":"))),
    }
    init["hash"] = "0" * 64
    broken = "&".join(f"{k}={v}" for k, v in init.items())
    r = await api_client.post(
        "/api/m/v1/auth/telegram", json={"init_data": broken, "link_code": ""}
    )
    assert r.status_code == 401


async def test_miniapp_stale_auth_date_401(api_client):
    stale = _make_init_data(424242, age=7200)
    r = await api_client.post(
        "/api/m/v1/auth/telegram", json={"init_data": stale, "link_code": ""}
    )
    assert r.status_code == 401
    assert "устарели" in r.json()["detail"]


async def test_miniapp_wrong_code_401_with_hint(api_client, fake_redis):
    r = await api_client.post(
        "/api/m/v1/auth/telegram",
        json={"init_data": _make_init_data(TG_ID), "link_code": "00000000"},
    )
    assert r.status_code == 401
    assert "Код" in r.json()["detail"]


async def test_miniapp_link_code_format_is_enforced(api_client, fake_redis):
    """Код другой длины не проходит даже на уровне схемы — иначе перебор
    идёт по 10**6 вариантов вместо 10**8."""
    r = await api_client.post(
        "/api/m/v1/auth/telegram",
        json={"init_data": _make_init_data(TG_ID), "link_code": "000000"},
    )
    assert r.status_code == 422
