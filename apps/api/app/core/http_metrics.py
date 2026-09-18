"""Собственный ASGI-middleware Prometheus-метрик HTTP (§12, §16 п.23/30).

prometheus-fastapi-instrumentator удалён: его routing несовместим со
starlette 0.5x+ (`_IncludedRouter` без `.path` → AttributeError и 500 на
каждый запрос). Имена метрик и лейблы сохранены прежними — alerts.yml и
дашборды Grafana остаются совместимыми. Отдача — `GET /metrics` в main.py
(generate_latest из дефолтного реестра).
"""
import time

from prometheus_client import Counter, Histogram

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["handler", "method", "status"],
)

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests",
    ["handler", "method", "status"],
)


def resolve_handler(scope: dict) -> str:
    """Шаблон маршрута ('/orders/{order_id}') вместо конкретного пути.

    getattr-guard: у служебных маршрутов path_format может отсутствовать;
    несматченный запрос (404) не оставляет в scope['route'] ничего.
    """
    route = scope.get("route")
    if route is None:
        return "unmatched"
    path = getattr(route, "path_format", None) or getattr(route, "path", None)
    return path or "unmatched"


class PrometheusMiddleware:
    """Считает длительность и количество запросов по шаблонам маршрутов."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status = "500"

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = str(message["status"])
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            handler = resolve_handler(scope)
            REQUEST_DURATION.labels(
                handler=handler, method=method, status=status
            ).observe(elapsed)
            REQUESTS_TOTAL.labels(
                handler=handler, method=method, status=status
            ).inc()
