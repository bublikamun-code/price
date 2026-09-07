"""Тесты связки Telegram (§16 п.27, §20): код привязки + bind/unbind.

Redis подменяется in-memory фейком (``_get_redis``, стиль ``_FakeLockRedis``
из test_notification_dispatch_idempotency), БД — тестовой session_factory
(подмена ``AsyncSessionLocal`` в сервисе: bind/unbind открывают сессию сами,
т.к. вызываются из автономного bot-процесса).
"""
import time
import uuid

import pytest

from app.models.enums import UserRole
from app.models.user import User
from app.services import telegram_auth as tg_auth
from tests.conftest import create_user

CHAT_ID = 777_001


class _FakeRedis:
    """In-memory эмуляция Redis GET/SET EX/GETDEL/DELETE/TTL для тестов."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deadlines: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        dl = self.deadlines.get(key)
        return key in self.values and (dl is None or dl > time.monotonic())

    def set(self, key, value, ex=None):
        self.values[key] = value
        if ex is not None:
            self.deadlines[key] = time.monotonic() + ex
        return True

    def get(self, key):
        return self.values[key] if self._alive(key) else None

    def delete(self, key):
        existed = self._alive(key)
        self.values.pop(key, None)
        self.deadlines.pop(key, None)
        return int(existed)

    def getdel(self, key):
        value = self.get(key)
        self.delete(key)
        return value

    def ttl(self, key) -> int:
        if not self._alive(key):
            return -2
        dl = self.deadlines.get(key)
        return -1 if dl is None else max(0, int(dl - time.monotonic()))


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(tg_auth, "_get_redis", lambda: fake)
    return fake


@pytest.fixture
def fake_db(monkeypatch, session_factory):
    monkeypatch.setattr(tg_auth, "AsyncSessionLocal", session_factory)
    return session_factory


async def _set_telegram(sf, user_id: uuid.UUID, chat_id: int | None) -> None:
    async with sf() as s:
        user = await s.get(User, user_id)
        user.telegram_id = chat_id
        await s.commit()


async def _get_telegram(sf, user_id: uuid.UUID) -> int | None:
    async with sf() as s:
        user = await s.get(User, user_id)
        return user.telegram_id


# ===========================================================================
# generate_link_code: формат, ключи, один активный код
# ===========================================================================
class TestGenerateLinkCode:
    async def test_code_format_keys_and_ttl(self, fake_redis, session_factory):
        user = await create_user(session_factory, email="tg1@x.by", role=UserRole.CLIENT)

        result = tg_auth.generate_link_code(user.id)

        assert set(result) == {"code", "expires_in"}  # контракт TelegramLinkCodeOut
        code = result["code"]
        assert len(code) == 6
        assert code.isdigit()  # формат ввода в Mini App: \d{6}
        assert result["expires_in"] == tg_auth.LINK_CODE_TTL_SEC == 900

        assert fake_redis.get(f"tg:link:{code}") == str(user.id)
        assert fake_redis.get(f"tg:linku:{user.id}") == code
        ttl = fake_redis.ttl(f"tg:link:{code}")
        assert 0 < ttl <= 900
        assert 0 < fake_redis.ttl(f"tg:linku:{user.id}") <= 900

    async def test_regenerate_deletes_old_code(self, fake_redis, session_factory):
        user = await create_user(session_factory, email="tg2@x.by", role=UserRole.CLIENT)

        first = tg_auth.generate_link_code(user.id)["code"]
        second = tg_auth.generate_link_code(user.id)["code"]

        assert first != second
        assert fake_redis.get(f"tg:link:{first}") is None  # старый код удалён
        assert fake_redis.get(f"tg:link:{second}") == str(user.id)
        assert fake_redis.get(f"tg:linku:{user.id}") == second

    async def test_codes_of_different_users_independent(self, fake_redis, session_factory):
        u1 = await create_user(session_factory, email="tg3@x.by", role=UserRole.CLIENT)
        u2 = await create_user(session_factory, email="tg4@x.by", role=UserRole.CLIENT)

        c1 = tg_auth.generate_link_code(u1.id)["code"]
        c2 = tg_auth.generate_link_code(u2.id)["code"]

        assert fake_redis.get(f"tg:link:{c1}") == str(u1.id)
        assert fake_redis.get(f"tg:link:{c2}") == str(u2.id)


# ===========================================================================
# bind_by_code: успех / одноразовость / ошибки
# ===========================================================================
class TestBindByCode:
    async def test_bind_success_persists_telegram_id(self, fake_redis, fake_db, session_factory):
        user = await create_user(session_factory, email="tg5@x.by", role=UserRole.CLIENT)
        code = tg_auth.generate_link_code(user.id)["code"]

        bound = await tg_auth.bind_by_code(code.lower(), CHAT_ID)  # регистр не важен

        assert bound.telegram_id == CHAT_ID
        assert await _get_telegram(session_factory, user.id) == CHAT_ID

    async def test_code_is_one_time_only(self, fake_redis, fake_db, session_factory):
        user = await create_user(session_factory, email="tg6@x.by", role=UserRole.CLIENT)
        code = tg_auth.generate_link_code(user.id)["code"]
        await tg_auth.bind_by_code(code, CHAT_ID)

        with pytest.raises(ValueError):
            await tg_auth.bind_by_code(code, CHAT_ID)  # код уже сожжён (GETDEL)

    async def test_unknown_or_expired_code_raises(self, fake_redis, fake_db):
        with pytest.raises(ValueError):
            await tg_auth.bind_by_code("DEADBEEF", CHAT_ID)
        with pytest.raises(ValueError):
            await tg_auth.bind_by_code("", CHAT_ID)

    async def test_bind_same_chat_is_idempotent_success(
        self, fake_redis, fake_db, session_factory
    ):
        user = await create_user(session_factory, email="tg7@x.by", role=UserRole.CLIENT)
        await _set_telegram(session_factory, user.id, CHAT_ID)
        code = tg_auth.generate_link_code(user.id)["code"]

        bound = await tg_auth.bind_by_code(code, CHAT_ID)

        assert bound.telegram_id == CHAT_ID  # успех без ошибки

    async def test_bind_other_chat_raises(self, fake_redis, fake_db, session_factory):
        user = await create_user(session_factory, email="tg8@x.by", role=UserRole.CLIENT)
        await _set_telegram(session_factory, user.id, 111)
        code = tg_auth.generate_link_code(user.id)["code"]

        with pytest.raises(ValueError, match="другому чату"):
            await tg_auth.bind_by_code(code, 222)

    async def test_bind_chat_taken_by_another_user_raises(
        self, fake_redis, fake_db, session_factory
    ):
        other = await create_user(session_factory, email="tg9@x.by", role=UserRole.CLIENT)
        user = await create_user(session_factory, email="tg10@x.by", role=UserRole.CLIENT)
        await _set_telegram(session_factory, other.id, CHAT_ID)
        code = tg_auth.generate_link_code(user.id)["code"]

        with pytest.raises(ValueError, match="другому аккаунту"):
            await tg_auth.bind_by_code(code, CHAT_ID)


# ===========================================================================
# unbind_by_chat
# ===========================================================================
class TestUnbindByChat:
    async def test_unbind_clears_telegram_id(self, fake_redis, fake_db, session_factory):
        user = await create_user(session_factory, email="tg11@x.by", role=UserRole.CLIENT)
        await _set_telegram(session_factory, user.id, CHAT_ID)

        assert await tg_auth.unbind_by_chat(CHAT_ID) is True
        assert await _get_telegram(session_factory, user.id) is None

    async def test_unbind_unknown_chat_returns_false(self, fake_redis, fake_db):
        assert await tg_auth.unbind_by_chat(123_456) is False
