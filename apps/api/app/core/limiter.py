"""Rate-limiting (slowapi). См. ARCHITECTURE_PLAN.md §11.

Лимит на login настраивается через settings.rate_limit_login (напр. "5/15minutes").
Redis обеспечивает общий счётчик между API workers; в тестах limiter отключается.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    enabled=True,
)
