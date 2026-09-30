"""Redis-кэш с теговой инвалидацией для каталога и рассчитанных цен (§7.2)."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.services.cache")

CATALOG_TAG = "catalog"
FILTERS_TAG = "filters"
# Скидки за объём (§16 п.41). В /api/v2 кэша ответов каталога нет вообще —
# кэшируются только лестницы brand_volume_tiers: данных мало, читаются на
# каждой строке корзины, меняются редко. Инвалидация — при любой правке ступени.
VOLUME_TIERS_TAG = "volume-tiers"


class TaggedCache:
    """JSON-кэш, где каждый ключ регистрируется в Redis set для каждого тега."""

    def __init__(self, redis: Redis, *, prefix: str = "price-portal") -> None:
        self.redis = redis
        self.prefix = prefix

    def data_key(self, key: str) -> str:
        return f"{self.prefix}:cache:{key}"

    def tag_key(self, tag: str) -> str:
        return f"{self.prefix}:tag:{tag}"

    async def get(self, key: str) -> Any | None:
        raw = await self.redis.get(self.data_key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl: int, tags: Iterable[str]) -> None:
        data_key = self.data_key(key)
        tag_keys = [self.tag_key(tag) for tag in dict.fromkeys(tags)]
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(data_key, json.dumps(value, ensure_ascii=False), ex=ttl)
            for tag_key in tag_keys:
                pipe.sadd(tag_key, data_key)
            await pipe.execute()

    async def invalidate_tags(self, *tags: str) -> int:
        tag_keys = [self.tag_key(tag) for tag in dict.fromkeys(tags)]
        if not tag_keys:
            return 0
        members = await self.redis.sunion(*tag_keys)
        data_keys = [m.decode("utf-8") if isinstance(m, bytes) else m for m in members]
        async with self.redis.pipeline(transaction=True) as pipe:
            if data_keys:
                pipe.delete(*data_keys)
            pipe.delete(*tag_keys)
            results = await pipe.execute()
        return int(results[0] if data_keys else 0)

    # ---- fail-open обёртки для прод-вызовов (§4: кэш не должен валить каталог) ----

    async def safe_get(self, key: str) -> Any | None:
        """Redis недоступен → «мимо кэша» (None), запрос обслуживается из БД."""
        try:
            return await self.get(key)
        except Exception as exc:
            log.warning("cache.get_failed", key=key, error=str(exc))
            return None

    async def safe_set(self, key: str, value: Any, *, ttl: int, tags: Iterable[str]) -> None:
        """Redis недоступен → просто не кэшируем (следующий запрос — мимо)."""
        try:
            await self.set(key, value, ttl=ttl, tags=tags)
        except Exception as exc:
            log.warning("cache.set_failed", key=key, error=str(exc))


_redis = Redis.from_url(settings.redis_url, decode_responses=True)
cache = TaggedCache(_redis, prefix=settings.cache_key_prefix)


def stable_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def catalog_key(*, user_id: Any, mode: str, filters: dict[str, Any]) -> str:
    return f"catalog:{user_id}:{mode}:{stable_hash(filters)}"


def product_key(*, user_id: Any, mode: str, sku: str) -> str:
    return f"product:{user_id}:{mode}:{sku}"


def user_tag(user_id: Any) -> str:
    return f"user:{user_id}"


# ---------- Валидация сессий (§11, §16 п.15: access-токен проверяет sid) ----------
# Короткий TTL: кэш — лишь оптимизация «горячего» пути (активные сессии);
# отзыв сессии немедленно удаляет ключ через invalidate_session(), поэтому
# протухшее «1» живёт не дольше TTL и не переживает logout/revoke.
SESSION_CACHE_TTL = 60


def session_cache_key(sid: Any) -> str:
    return f"{settings.cache_key_prefix}:session:{sid}"


async def get_session_cached(sid: Any) -> str | None:
    """«1» активна / «0» отозвана / None — мимо кэша (Redis down или нет ключа)."""
    try:
        raw = await cache.redis.get(session_cache_key(sid))
    except Exception as exc:
        log.warning("cache.session_get_failed", sid=str(sid), error=str(exc))
        return None
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


async def set_session_cached(sid: Any, active: bool) -> None:
    try:
        await cache.redis.setex(session_cache_key(sid), SESSION_CACHE_TTL, "1" if active else "0")
    except Exception as exc:
        log.warning("cache.session_set_failed", sid=str(sid), error=str(exc))


async def invalidate_session(sid: Any) -> None:
    """Вызывается при отзыве сессии (logout/refresh/revoke) — fail-open."""
    try:
        await cache.redis.delete(session_cache_key(sid))
    except Exception as exc:
        log.warning("cache.session_del_failed", sid=str(sid), error=str(exc))


# ---------- Блокировка аккаунта после N неудачных входов (H4) ----------
# Счётчик неудач по паре email+IP в Redis; при достижении лимита вход с этого
# IP блокируется на login_lockout_minutes. Ключ email+IP (P2 §3.1): чистый
# email-ключ позволял бы атакующему лочить произвольный чужой аккаунт спамом
# неудач. Redis down → fail-open (не блокируем вход: иначе авария Redis
# превратилась бы в DoS всех логинов; IP rate-limit остаётся).
def login_fail_key(email: str, ip: str | None = None) -> str:
    email_part = email.strip().lower()
    if ip:
        return f"{settings.cache_key_prefix}:login_fail:{email_part}:{ip}"
    return f"{settings.cache_key_prefix}:login_fail:{email_part}"


async def is_account_locked(email: str, max_attempts: int, ip: str | None = None) -> bool:
    try:
        raw = await cache.redis.get(login_fail_key(email, ip))
    except Exception as exc:
        log.warning("cache.lockout_get_failed", email=email, error=str(exc))
        return False
    if raw is None:
        return False
    try:
        return int(raw) >= max_attempts
    except (ValueError, TypeError):
        return False


async def record_login_failure(
    email: str, max_attempts: int, lockout_minutes: int, ip: str | None = None
) -> int:
    """Инкрементирует счётчик неудач; TTL = окно блокировки. Возвращает новый счётчик."""
    key = login_fail_key(email, ip)
    try:
        count = int(await cache.redis.incr(key))
        await cache.redis.expire(key, lockout_minutes * 60)
        return count
    except Exception as exc:
        log.warning("cache.lockout_incr_failed", email=email, error=str(exc))
        return 0


async def clear_login_failures(email: str, ip: str | None = None) -> None:
    """Успешный вход сбрасывает счётчик неудач."""
    try:
        await cache.redis.delete(login_fail_key(email, ip))
    except Exception as exc:
        log.warning("cache.lockout_del_failed", email=email, error=str(exc))


async def invalidate_tags(*tags: str) -> int:
    """Best-effort invalidation: Redis outage must not break committed mutations."""
    try:
        return await cache.invalidate_tags(*tags)
    except Exception as exc:
        log.warning("cache.invalidate_failed", tags=tags, error=str(exc))
        return 0
