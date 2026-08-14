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


async def invalidate_tags(*tags: str) -> int:
    """Best-effort invalidation: Redis outage must not break committed mutations."""
    try:
        return await cache.invalidate_tags(*tags)
    except Exception as exc:
        log.warning("cache.invalidate_failed", tags=tags, error=str(exc))
        return 0
