"""Интеграция с 1С (§18): контракт, заглушка, HTTP-клиент и фабрика.

Публичный вход пакета — этот модуль::

    from app.integrations.one_c import get_one_c_client

Состояние на старте приложения: ``get_one_c_client()`` отдаёт
``StubOneCClient``, если обмен не настроен, и ``HttpOneCClient`` с таймаутом —
если настроен. Приложение стартует в обоих случаях (§18).
"""
from app.integrations.one_c.client import OneCClient
from app.integrations.one_c.errors import (
    NOT_CONFIGURED_HINT,
    OneCAuthError,
    OneCError,
    OneCNotConfiguredError,
    OneCResponseError,
    OneCTransportError,
)
from app.integrations.one_c.factory import (
    create_one_c_client,
    describe_one_c_state,
    get_one_c_client,
    missing_outbound_settings,
    reset_one_c_client,
)
from app.integrations.one_c.http_client import HttpOneCClient
from app.integrations.one_c.schemas import (
    OrderExportRequest,
    OrderExportResult,
    OrderStatusRequest,
    OrderStatusResult,
    PriceImportSummary,
    StockImportSummary,
)
from app.integrations.one_c.stub import NOT_CONFIGURED_MESSAGE, StubOneCClient

__all__ = [
    "NOT_CONFIGURED_HINT",
    "NOT_CONFIGURED_MESSAGE",
    "HttpOneCClient",
    "OneCAuthError",
    "OneCClient",
    "OneCError",
    "OneCNotConfiguredError",
    "OneCResponseError",
    "OneCTransportError",
    "OrderExportRequest",
    "OrderExportResult",
    "OrderStatusRequest",
    "OrderStatusResult",
    "PriceImportSummary",
    "StockImportSummary",
    "StubOneCClient",
    "create_one_c_client",
    "describe_one_c_state",
    "get_one_c_client",
    "missing_outbound_settings",
    "reset_one_c_client",
]