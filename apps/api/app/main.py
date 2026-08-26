"""Точка входа FastAPI приложения.

См. ARCHITECTURE_PLAN.md §4 (Clean Architecture), §6 (API), §11 (Security).
"""
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import miniapp
from app.api.v1 import health
from app.api.v1.integrations import one_c
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.deps import validate_csrf
from app.core.http_metrics import PrometheusMiddleware
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
# Swagger UI / OpenAPI отключаются в production (§16 п.15: security hardening)
_docs_url = None if settings.env == "prod" else "/docs"
_redoc_url = None if settings.env == "prod" else "/redoc"
_openapi_url = None if settings.env == "prod" else "/openapi.json"

app = FastAPI(
    title="B2B Price Portal API",
    description=(
        "Клиентский портал с динамическими прайс-листами. "
        "Каноничная спека — ARCHITECTURE_PLAN.md / SITEMAP.md."
    ),
    version="0.1.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    lifespan=lifespan,
)


# ---------- Rate limiting (slowapi) ----------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------- Middleware: CORS ----------
# M3: только реально используемые методы/заголовки (а не «*»), origins — из настроек.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)


# ---------- Middleware: CSRF для cookie-аутентификации ----------
class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            validate_csrf(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)


app.add_middleware(CSRFMiddleware)


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


# ---------- Middleware: security-заголовки (L3) ----------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if settings.content_security_policy:
            # CSP в режиме Report-Only: браузер только репортит, ничего не блокирует
            # (§16 п.30). Enforcing — после анализа отчётов на проде; пустая строка
            # в конфиге полностью выключает заголовок.
            response.headers.setdefault(
                "Content-Security-Policy-Report-Only", settings.content_security_policy
            )
        if request.cookies.get("access_token"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---------- Middleware: глобальный лимит тела (M6) ----------
# JSON-запросы ограничены 1 МБ; multipart-загрузки (CSV/фото/файлы) не трогаем —
# у них свои потоковые лимиты в эндпоинтах (100/200/20 МБ).
class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    MAX_JSON_BYTES = 1 * 1024 * 1024

    async def dispatch(self, request: Request, call_next):
        ctype = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" not in ctype:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.MAX_JSON_BYTES:
                return JSONResponse(
                    status_code=413, content={"detail": "Слишком большой запрос"}
                )
        return await call_next(request)


app.add_middleware(MaxBodySizeMiddleware)


# ---------- Prometheus-метрики /metrics (§12, §16 п.23) ----------
# M2: в prod порт api не публикуется (docker-compose.prod.yml, ports: !reset []),
# поэтому /metrics доступен только во внутренней сети (Prometheus) — наружу не ходит.
# Собственный ASGI-middleware вместо prometheus-fastapi-instrumentator (§16 п.30):
# его routing несовместим со starlette 0.5x (_IncludedRouter без .path → 500 на
# каждый запрос). Имена метрик/лейблов сохранены — алёрты alerts.yml и дашборды
# Grafana (http_request_duration_seconds{handler,method,status}) совместимы.
app.add_middleware(PrometheusMiddleware)


@app.get("/metrics", include_in_schema=False, tags=["root"])
async def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
# 1С: subroute /api/integrations/1c/** — отдельный include на app, вне /api/v1
# (§18.1, §16 п.24; заглушки 501 до пост-MVP)
app.include_router(one_c.router, prefix="/api")
# Telegram Mini App: subroute /api/m/v1/** (§6, §16 п.27); данные — из /api/v1/**
app.include_router(miniapp.router, prefix="/api")


# ---------- Root ----------
@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {"app": "B2B Price Portal", "version": "0.1.0", "docs": "/docs"}
