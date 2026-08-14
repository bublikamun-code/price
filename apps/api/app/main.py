"""Точка входа FastAPI приложения.

См. ARCHITECTURE_PLAN.md §4 (Clean Architecture), §6 (API), §11 (Security).
"""
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router
from app.api.v1 import health
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger, setup_logging
from app.schemas import APIError, ErrorResponse


# ---------- Lifespan (стартовые/завершающие действия) ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = get_logger("app.main")
    log.info("app.starting", env=settings.env, app=settings.app_name)
    yield
    log.info("app.stopping", env=settings.env)


# ---------- App ----------
app = FastAPI(
    title="B2B Price Portal API",
    description=(
        "Клиентский портал с динамическими прайс-листами. "
        "Каноничная спека — ARCHITECTURE_PLAN.md / SITEMAP.md."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# ---------- Rate limiting (slowapi) ----------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------- Middleware: CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Middleware: correlation id + логирование запросов ----------
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestContextMiddleware)


# ---------- Глобальный обработчик ошибок (единый envelope) ----------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log = get_logger("app.errors")
    log.exception("unhandled_error", error=str(exc))
    err = ErrorResponse(code="INTERNAL_ERROR", message="Внутренняя ошибка сервера")
    return JSONResponse(status_code=500, content=APIError(error=err).model_dump())


# ---------- Роутеры ----------
app.include_router(health.router)          # /healthz, /readyz — на root (вне /api/v1)
app.include_router(api_router)


# ---------- Root ----------
@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {"app": "B2B Price Portal", "version": "0.1.0", "docs": "/docs"}
