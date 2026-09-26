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

    def incr(self, key) -> int:
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    def expire(self, key, seconds) -> bool:
        if key not in self.values:
            return False
        self.deadlines[key] = time.monotonic() + seconds
        return True


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
        assert len(code) == tg_auth.LINK_CODE_LENGTH == 8
        assert code.isdigit()  # формат ввода в Mini App: \d{8}
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

    async def test_successful_consume_clears_reverse_index(self, fake_redis, session_factory):
        """Обратный индекс живёт только пока код актуален: иначе ключи копятся
        в Redis до конца TTL."""
        user = await create_user(session_factory, email="tg-clear@x.by", role=UserRole.CLIENT)
        code = tg_auth.generate_link_code(user.id)["code"]

        assert tg_auth.consume_link_code(code) == user.id

        assert fake_redis.get(f"tg:linku:{user.id}") is None
        assert fake_redis.get(f"tg:link:{code}") is None

    async def test_consume_is_one_time_only(self, fake_redis, session_factory):
        user = await create_user(session_factory, email="tg-once@x.by", role=UserRole.CLIENT)
        code = tg_auth.generate_link_code(user.id)["code"]

        assert tg_auth.consume_link_code(code) == user.id
        assert tg_auth.consume_link_code(code) is None


# ===========================================================================
# consume_link_code: троттлинг перебора по Telegram-аккаунту
# ===========================================================================
class TestConsumeLinkCodeThrottle:
    async def test_wrong_codes_counted_per_telegram_account(self, fake_redis):
        scope = "tg:424242"

        for expected in range(1, tg_auth.LINK_CODE_MAX_ATTEMPTS):
            assert tg_auth.consume_link_code("99999999", throttle_scope=scope) is None
            assert fake_redis.get(f"tg:linktry:{scope}") == str(expected)

    async def test_rate_limited_after_max_attempts(self, fake_redis):
        scope = "tg:424242"
        for _ in range(tg_auth.LINK_CODE_MAX_ATTEMPTS - 1):
            assert tg_auth.consume_link_code("99999999", throttle_scope=scope) is None

        with pytest.raises(tg_auth.LinkCodeRateLimited):
            tg_auth.consume_link_code("99999999", throttle_scope=scope)

    async def test_throttle_is_per_account_not_global(self, fake_redis):
        """Чужой перебор не должен блокировать честного пользователя."""
        attacker = "tg:1"
        victim = "tg:2"
        for _ in range(tg_auth.LINK_CODE_MAX_ATTEMPTS - 1):
            tg_auth.consume_link_code("00000000", throttle_scope=attacker)
        with pytest.raises(tg_auth.LinkCodeRateLimited):
            tg_auth.consume_link_code("00000000", throttle_scope=attacker)

        assert tg_auth.consume_link_code("00000000", throttle_scope=victim) is None

    async def test_correct_code_resets_throttle(self, fake_redis, session_factory):
        """Опечатка не должна наказывать: после верного кода лимит сброшен."""
        user = await create_user(session_factory, email="tg-reset@x.by", role=UserRole.CLIENT)
        code = tg_auth.generate_link_code(user.id)["code"]
        scope = "tg:424242"
        for _ in range(tg_auth.LINK_CODE_MAX_ATTEMPTS - 1):
            tg_auth.consume_link_code("99999999", throttle_scope=scope)

        assert tg_auth.consume_link_code(code, throttle_scope=scope) == user.id

        assert fake_redis.get(f"tg:linktry:{scope}") is None
        assert tg_auth.consume_link_code(code, throttle_scope=scope) is None

    async def test_no_scope_means_no_throttle(self, fake_redis):
        """Бот вызывает без scope: там своя защита, лимит не должен мешать."""
        for _ in range(tg_auth.LINK_CODE_MAX_ATTEMPTS + 3):
            assert tg_auth.consume_link_code("99999999") is None


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
