"""Health-check эндпоинты.

- /healthz — liveness (процесс жив)
- /readyz  — readiness (БД + Redis + S3 доступны)
"""
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Readiness probe: проверяет БД (Redis/S3 добавим по мере реализации)."""
    checks: dict[str, str] = {"db": "ok"}
    http_status = status.HTTP_200_OK

    # --- PostgreSQL ---
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar_one()
    except SQLAlchemyError:
        checks["db"] = "fail"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    # Redis/S3 проверки будут добавлены в Этапе 3+ (см. ARCHITECTURE_PLAN.md §12)

    # L1: не светим окружение (dev/prod) наружу — это помогает fingerprinting.
    body = {"status": "ok" if http_status == 200 else "fail", "checks": checks}
    return JSONResponse(status_code=http_status, content=body)
