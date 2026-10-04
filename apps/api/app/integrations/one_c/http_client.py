"""Реальный клиент 1С: исходящий обмен портал → 1С по HTTP (§18).

Намеренно тонкий: он переводит вызовы протокола ``OneCClient`` в HTTP-запросы к
сервису 1С и переводит ответы обратно в DTO CommerceML. Вся бизнес-логика
(отбор заказов, применение прайса) — в сервисах, здесь её нет.

Правила, зафиксированные в коде:
  * **Таймаут обязателен.** ``httpx`` по умолчанию ждёт бесконечно, а обмен
    с 1С в нормальном режиме укладывается в секунды; таймаут берётся из
    ``INTEGRATION_1C_TIMEOUT_SEC`` и никогда не бывает нулевым.
  * **Соединение ленивое.** Клиент httpx создаётся при первом обмене, а не в
    конструкторе: иначе неверные настройки (URL) роняли бы старт приложения.
  * **Секрет не логируется.** Токен уходит заголовком ``X-Integration-Token``
    и не попадает в логи и сообщения об ошибках.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.core.logging import get_logger
from app.integrations.one_c.errors import (
    OneCAuthError,
    OneCResponseError,
    OneCTransportError,
)
from app.integrations.one_c.schemas import (
    OrderExportRequest,
    OrderExportResult,
    OrderStatusRequest,
    OrderStatusResult,
)
from app.schemas.commerceml.orders import OrderDocument

log = get_logger("app.integrations.one_c.http")

#: Куда ходим на стороне 1С. Пути соответствуют §18.2.
ORDERS_EXPORT_PATH = "/orders/export"
ORDERS_STATUS_PATH = "/orders/status"

DEFAULT_TIMEOUT_SEC = 10.0


class HttpOneCClient:
    """Клиент 1С поверх httpx.AsyncClient."""

    transport = "http"

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        # timeout=0 в httpx означает «ждать вечно» — для фонового обмена это
        # хуже, чем ошибка: воркер залипнет. Ставим положительный минимум.
        self.timeout_sec = max(float(timeout_sec), 0.1)
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return True

    def describe(self) -> str:
        return f"OneCClient[http]: {self.base_url} (timeout={self.timeout_sec}s)"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_sec,
                headers=self._headers(),
            )
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Integration-Token"] = self.token
        return headers

    async def export_orders(self, request: OrderExportRequest) -> OrderExportResult:
        """``GET {base}/orders/export?since=…&schema_version=…`` → заказы."""
        params = {"schema_version": request.schema_version, "limit": request.limit}
        if request.since is not None:
            params["since"] = request.since.astimezone(timezone.utc).isoformat()
        payload = await self._request("GET", ORDERS_EXPORT_PATH, params=params)
        return OrderExportResult(
            orders=[OrderDocument.model_validate(item) for item in _items(payload)],
            schema_version=str(payload.get("schema_version", request.schema_version)),
        )

    async def push_order_status(self, request: OrderStatusRequest) -> OrderStatusResult:
        """``POST {base}/orders/status`` — возврат статуса заказа."""
        payload = await self._request(
            "POST",
            ORDERS_STATUS_PATH,
            json=request.change.model_dump(mode="json"),
        )
        change = request.change
        return OrderStatusResult(
            external_id=str(payload.get("external_id", change.external_id)),
            accepted=bool(payload.get("accepted", True)),
            registered_at=_parse_dt(payload.get("registered_at")) or datetime.now(timezone.utc),
            schema_version=str(payload.get("schema_version", request.schema_version)),
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, object] | None = None,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Выполнить запрос и вернуть JSON-объект, разложив ошибки по типам."""
        client = self._http()
        try:
            response = await client.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            raise OneCTransportError(
                f"1С не ответила за {self.timeout_sec} с ({path})"
            ) from exc
        except httpx.HTTPError as exc:
            raise OneCTransportError(f"Сбой связи с 1С ({path}): {exc}") from exc

        if response.status_code in (401, 403):
            raise OneCAuthError(
                f"1С отклонила запрос {path}: код {response.status_code} "
                "(проверьте токен и allowlist IP)"
            )
        if response.status_code >= 400:
            raise OneCResponseError(
                f"1С вернула ошибку на {path}: код {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OneCResponseError(
                f"1С вернула не-JSON на {path} (возможно, HTML-ошибка)"
            ) from exc
        if not isinstance(payload, dict):
            raise OneCResponseError(f"Неожиданный формат ответа 1С на {path}")
        return payload


def _items(payload: dict[str, object]) -> list[dict[str, object]]:
    """Достать список позиций из ответа 1С (``items`` или ``orders``)."""
    raw = payload.get("items", payload.get("orders"))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = ["DEFAULT_TIMEOUT_SEC", "ORDERS_EXPORT_PATH", "ORDERS_STATUS_PATH", "HttpOneCClient"]