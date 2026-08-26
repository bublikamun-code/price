"""Кэш каталога/цен и теговая инвалидация (§7.2)."""
import uuid

import pytest

from app.services.cache import TaggedCache, catalog_key, product_key, user_tag
from app.services import cache as cache_module


class MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.ops = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def set(self, *args, **kwargs): self.ops.append(("set", args, kwargs))
    def sadd(self, *args, **kwargs): self.ops.append(("sadd", args, kwargs))
    def delete(self, *args, **kwargs): self.ops.append(("delete", args, kwargs))

    async def execute(self):
        results = []
        for name, args, kwargs in self.ops:
            results.append(await getattr(self.redis, name)(*args, **kwargs))
        return results


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1
    async def sunion(self, *keys): return set().union(*(self.sets.get(k, set()) for k in keys))
    async def delete(self, *keys):
        count = 0
        for key in keys:
            count += int(key in self.values) + int(key in self.sets)
            self.values.pop(key, None)
            self.sets.pop(key, None)
        return count
    def pipeline(self, transaction=True): return MemoryPipeline(self)


@pytest.mark.asyncio
async def test_cache_miss_hit_and_tag_invalidation():
    cache = TaggedCache(MemoryRedis(), prefix="test")
    assert await cache.get("catalog:key") is None
    await cache.set("catalog:key", {"data": [1]}, ttl=300, tags=["catalog", "user:1"])
    assert await cache.get("catalog:key") == {"data": [1]}
    assert await cache.invalidate_tags("catalog") == 1
    assert await cache.get("catalog:key") is None


def test_catalog_keys_are_partitioned_by_user_mode_and_filters():
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    base = {"q": "box", "page": 1, "brand": ["a"]}
    keys = {
        catalog_key(user_id=user_a, mode="fixed", filters=base),
        catalog_key(user_id=user_b, mode="fixed", filters=base),
        catalog_key(user_id=user_a, mode="nbrb_current", filters=base),
        catalog_key(user_id=user_a, mode="fixed", filters={**base, "page": 2}),
    }
    assert len(keys) == 4
    assert user_tag(user_a) != user_tag(user_b)
    assert product_key(user_id=user_a, mode="fixed", sku="A") != product_key(
        user_id=user_a, mode="nbrb_current", sku="A"
    )


class BrokenRedis:
    """Имитация лежащего Redis: любое обращение — ConnectionError."""

    async def get(self, key):
        raise ConnectionError("redis down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    async def sadd(self, key, value):
        raise ConnectionError("redis down")

    async def sunion(self, *keys):
        raise ConnectionError("redis down")

    async def delete(self, *keys):
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_fail_open_when_redis_down():
    """Каталог не должен падать при недоступном Redis (§4): safe_* молча
    деградируют в «мимо кэша», best-effort invalidate возвращает 0."""
    broken = TaggedCache(BrokenRedis(), prefix="test")
    assert await broken.safe_get("catalog:key") is None
    await broken.safe_set("catalog:key", {"data": []}, ttl=300, tags=["catalog"])  # не raise

    cache_module.cache.redis = BrokenRedis()
    try:
        assert await cache_module.invalidate_tags("catalog", "user:1") == 0
    finally:
        # восстановим рабочий клиент (conftest всё равно подменит на свой)
        from app.core.config import settings
        from redis.asyncio import Redis

        cache_module.cache.redis = Redis.from_url(settings.redis_url, decode_responses=True)
