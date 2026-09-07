"""Health-check эндпоинты.

- /healthz — liveness (процесс жив)
- /readyz  — readiness (БД + Redis + S3 доступны)
"""
from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.services import storage
from app.services.storage import StorageError

router = APIRouter(tags=["health"])

# Отдельный клиент для пробы Redis: короткие таймауты (socket), чтобы
# недоступный Redis не подвешивал readyz на дефолтные секунды.
_readiness_redis = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Readiness probe: 200 только если живы все компоненты (БД + Redis + S3);
    при деградации — 503 и перечень отказавших в ``checks``.
    """
    checks: dict[str, str] = {"db": "ok", "redis": "ok", "s3": "ok"}
    http_status = status.HTTP_200_OK

    # --- PostgreSQL ---
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar_one()
    except SQLAlchemyError:
        checks["db"] = "fail"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    # --- Redis ---
    try:
        await _readiness_redis.ping()
    except (RedisError, ConnectionError, OSError, TimeoutError):
        checks["redis"] = "fail"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    # --- S3 / MinIO (sync-клиент → threadpool, event loop не блокируется) ---
    try:
        await run_in_threadpool(storage.check_connection)
    except (StorageError, ConnectionError, OSError):
        checks["s3"] = "fail"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    # L1: не светим окружение (dev/prod) наружу — это помогает fingerprinting.
    body = {"status": "ok" if http_status == 200 else "fail", "checks": checks}
    return JSONResponse(status_code=http_status, content=body)
