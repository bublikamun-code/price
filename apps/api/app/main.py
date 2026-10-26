"""Точка входа FastAPI приложения.

См. ARCHITECTURE_PLAN.md §4 (Clean Architecture), §6 (API), §11 (Security).
"""
import hmac
import ipaddress
import re
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import health
from app.api.v1.integrations import one_c
from app.api.v1.router import api_router
from app.api.v2.errors import (
    from_domain_error,
    http_problem_response,
    is_v2_request,
    problem_response,
    request_id_for,
    validation_problem_response,
)
from app.api.v2.router import api_router as v2_router
from app.api.v2.errors import V2ProblemError
from app.core.config import settings
from app.core.deps import validate_csrf
from app.integrations.one_c import get_one_c_client

try:
    from app.core.http_metrics import PrometheusMiddleware
except ImportError:
    PrometheusMiddleware = None  # type: ignore[assignment,misc]
from app.core.limiter import limiter
from app.core.logging import get_logger, setup_logging
from app.schemas import APIError, ErrorResponse

# Модульный логгер для middleware (RealIP): logging настраивается в lifespan,
# structlog-вызовы до него буферизуются дефолтной конфигурацией.
log = get_logger("app.main")


# ---------- Lifespan (стартовые/завершающие действия) ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = get_logger("app.main")
    log.info("app.starting", env=settings.env, app=settings.app_name)
    one_c_client = getattr(app.state, "one_c_client", None)
    if one_c_client is not None:
        # Диагностика стенда: «stub» = обмен с 1С не настроен, ручки
        # /api/integrations/1c/** отвечают 503/501 (§18).
        log.info(
            "one_c.client_ready",
            transport=one_c_client.transport,
            configured=one_c_client.configured,
        )
    yield
    # Корректное закрытие пула соединений БД (P2 §3.2): без dispose uvicorn
    # при остановке шумит «Unclosed connection» и держит сокеты до GC.
    from app.db.session import engine

    await engine.dispose()
    log.info("app.stopped", env=settings.env, app=settings.app_name)


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

# ---------- 1С: клиент обмена (§18) ----------
# Фабрика выбирает реализацию по настройкам: настроено → HttpOneCClient с
# таймаутом, не настроено → StubOneCClient. Фабрика не бросает исключений,
# поэтому приложение стартует в обоих случаях; «не настроено» оператор видит
# в логе старта и в ответах /api/integrations/1c/** (503/501), а не в трейсе.
app.state.one_c_client = get_one_c_client()


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    if is_v2_request(request):
        return problem_response(
            request,
            code="RATE_LIMITED",
            status=429,
            title="Слишком много запросов",
            detail="Превышен лимит количества запросов",
            headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
        )
    return _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# ---------- Middleware: CORS ----------
# M3: только реально используемые методы/заголовки (а не «*»), origins — из настроек.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "Idempotency-Key",
        "X-CSRF-Token",
        "X-Request-ID",
    ],
)


# ---------- Middleware: CSRF для cookie-аутентификации ----------
class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            validate_csrf(request)
        except HTTPException as exc:
            if is_v2_request(request):
                return http_problem_response(request, exc)
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)


app.add_middleware(CSRFMiddleware)


# ---------- Middleware: correlation id + логирование запросов ----------
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Клиентский X-Request-ID возвращается эхом в ответе, поэтому принимаем
        # только короткий идентификатор из безопасного алфавита: иначе в ответ
        # попадает произвольная строка (инъекция в логи, развод заголовков).
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
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
def _is_https(request: Request) -> bool:
    """Схема внешнего запроса. За nginx/PM2 TLS терминируется на edge, поэтому
    ориентируемся на заголовок прокси, а не на собственный socket uvicorn."""
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return proto.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # CORP: JSON API не встраивается кросс-сайтом (img/frame) — фронт
        # ходит same-origin, нативным клиентам CORP безразличен (FP-11).
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if settings.permissions_policy:
            response.headers.setdefault("Permissions-Policy", settings.permissions_policy)
        if settings.hsts_max_age > 0 and _is_https(request):
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={settings.hsts_max_age}"
            )
        if settings.content_security_policy:
            # CSP в enforcing-режиме (§16 п.30): браузер блокирует нарушения.
            # Политика допускает 'unsafe-inline' для script/style — Nuxt SSR
            # инлайнит скрипты гидратации; внешних ресурсов фронт не грузит.
            # Пустая строка в конфиге полностью выключает заголовок.
            response.headers.setdefault(
                "Content-Security-Policy", settings.content_security_policy
            )
        # no-store для аутентифицированных ответов — и cookie-сессии (web),
        # и Bearer-клиенты (нативные приложения, FP-11): в общие кэши не должно
        # попадать ни то, ни другое.
        if (
            request.cookies.get("auth_token")
            or request.cookies.get("access_token")
            or request.headers.get("authorization")
        ):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---------- Middleware: реальный IP клиента (FP-10b) ----------
class RealIPMiddleware(BaseHTTPMiddleware):
    """``request.client`` = реальный адрес клиента из ``X-Real-IP``.

    Uvicorn 0.30 умеет доверять X-Forwarded-For только точным IP
    (``--forwarded-allow-ips`` — строковое множество, без CIDR), а IP
    compose-контейнера nginx плавает при пересоздании. Доверие решаем
    на уровне приложения: заголовок принимается только если ПИР из
    приватной сети (docker-сеть, loopback). Безопасно: единственный
    ingress — nginx, который всегда ставит ``X-Real-IP $remote_addr``
    и перезаписывает клиентские подделки; наружу api не публикуется
    (compose ports), поэтому приватный пир — это всегда свой прокси.
    """

    async def dispatch(self, request: Request, call_next):
        client = request.scope.get("client")
        if client:
            try:
                peer_is_private = ipaddress.ip_address(client[0]).is_private
            except ValueError:
                peer_is_private = False
            if peer_is_private:
                real = request.headers.get("x-real-ip", "").strip()
                if real:
                    try:
                        # Порт теряется сознательно: slowapi/аудит работают
                        # с адресом, а не с сокетом.
                        request.scope["client"] = (str(ipaddress.ip_address(real)), 0)
                    except ValueError:
                        log.warning("realip.bad_header", value=real[:64])
        return await call_next(request)


app.add_middleware(RealIPMiddleware)


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
                if is_v2_request(request):
                    return problem_response(
                        request,
                        code="PAYLOAD_TOO_LARGE",
                        status=413,
                        title="Слишком большой запрос",
                        detail="Размер JSON-запроса превышает допустимый предел",
                        headers={"X-Request-ID": request_id_for(request)},
                    )
                return JSONResponse(
                    status_code=413, content={"detail": "Слишком большый запрос"}
                )
        return await call_next(request)


app.add_middleware(MaxBodySizeMiddleware)


# ---------- Prometheus-метрики /metrics (§12, §16 п.23) ----------
# M2: в prod порт api не публикуется (docker-compose.prod.yml, ports: !reset []),
# поэтому /metrics доступен только во внутренней сети (Prometheus) — наружу не ходит.
# Собственный ASGI-middleware вместо prometheus-fastapi-instrumentator (§16 п.30):
if PrometheusMiddleware is not None:
    app.add_middleware(PrometheusMiddleware)


@app.get("/metrics", include_in_schema=False, tags=["root"])
async def prometheus_metrics(request: Request) -> Response:
    if PrometheusMiddleware is None:
        return Response("Metrics not available", status_code=501)
    # В prod метрики не публикуются: без токена ручка отвечает 404 (как /docs),
    # с токеном — только по точному совпадению заголовка. В dev/staging
    # поведение прежнее, чтобы локальный стенд и сборщик метрик работали.
    if settings.is_prod:
        expected = settings.metrics_token
        supplied = request.headers.get("X-Metrics-Token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return Response("Not Found", status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------- API v2 errors: RFC 9457-style, v1 remains unchanged ----------
@app.exception_handler(V2ProblemError)
async def v2_problem_handler(request: Request, exc: V2ProblemError):
    return from_domain_error(request, exc)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler_for_v2(request: Request, exc: StarletteHTTPException):
    if is_v2_request(request):
        return http_problem_response(request, exc)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler_for_v2(request: Request, exc: RequestValidationError):
    if is_v2_request(request):
        return validation_problem_response(request, exc)
    return await request_validation_exception_handler(request, exc)


# ---------- Глобальный обработчик ошибок (единый envelope) ----------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log = get_logger("app.errors")
    log.exception("unhandled_error", error=str(exc))
    if is_v2_request(request):
        return problem_response(
            request,
            code="INTERNAL_ERROR",
            status=500,
            title="Внутренняя ошибка сервера",
            detail="Внутренняя ошибка сервера",
        )
    err = ErrorResponse(code="INTERNAL_ERROR", message="Внутренняя ошибка сервера")
    return JSONResponse(status_code=500, content=APIError(error=err).model_dump())


# ---------- Роутеры ----------
app.include_router(health.router)          # /healthz, /readyz — на root (вне /api/v1)
app.include_router(api_router)
app.include_router(v2_router)
# 1С: subroute /api/integrations/1c/** — отдельный include на app, вне /api/v1.
# Модуль интеграции — наш собственный код, include не должен быть опциональным
# (иначе ручки молча исчезли бы из схемы). Но старт приложения важнее: при любой
# ошибке логируем и едем без ручек, а не падаем.
try:
    app.include_router(one_c.router, prefix="/api")
except Exception:  # pragma: no cover - защитный контур старта
    get_logger("app.main").error("one_c.router_include_failed", exc_info=True)
# Telegram Mini App: subroute /api/m/v1/** (fail-fast: модуль обязателен)
from app.api import miniapp  # noqa: E402

app.include_router(miniapp.router, prefix="/api")


# ---------- Root ----------
@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    payload = {"app": "B2B Price Portal", "version": "0.1.0"}
    if settings.env != "prod":
        # В проде Swagger скрыт, чтобы не рекламировать внутренний API-контракт.
        payload["docs"] = "/docs"
    return payload
