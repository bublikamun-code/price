"""DTO обмена с 1С: запросы и ответы клиента (слой интеграции).

Разделены с документами CommerceML (``app/schemas/commerceml``): там — что
передаём, здесь — как упаковано в конкретный вызов клиента. Слой обмена не
знает про БД и ORM-модели заказов — он говорит на языке CommerceML.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.commerceml.common import SCHEMA_VERSION
from app.schemas.commerceml.orders import OrderDocument, OrderStatusChange


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrderExportRequest:
    """Запрос выгрузки заказов в 1С (§18.2 ``GET orders/export?since=``)."""

    __slots__ = ("since", "limit", "schema_version")

    def __init__(
        self,
        since: datetime | None = None,
        limit: int = 100,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.since = since
        self.limit = limit
        self.schema_version = schema_version


class OrderExportResult:
    """Ответ 1С на выгрузку заказов."""

    __slots__ = ("orders", "exported_at", "schema_version")

    def __init__(
        self,
        orders: list[OrderDocument],
        exported_at: datetime | None = None,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.orders = orders
        self.exported_at = exported_at or _utcnow()
        self.schema_version = schema_version


class OrderStatusRequest:
    """Запрос возврата статуса заказа в 1С (§18.2 ``POST orders/status``)."""

    __slots__ = ("change", "schema_version")

    def __init__(
        self,
        change: OrderStatusChange,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.change = change
        self.schema_version = schema_version


class OrderStatusResult:
    """Ответ 1С на возврат статуса заказа."""

    __slots__ = ("external_id", "accepted", "registered_at", "schema_version")

    def __init__(
        self,
        external_id: str,
        accepted: bool,
        registered_at: datetime | None = None,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.external_id = external_id
        self.accepted = accepted
        self.registered_at = registered_at or _utcnow()
        self.schema_version = schema_version


class PriceImportSummary:
    """Итог приёма прайса из 1С (§18.2 ``POST prices/import``).

    Заполняется сервисом импорта при реальной реализации; на заглушках не
    используется, но контракт уже зафиксирован.
    """

    __slots__ = ("received", "applied", "rejected", "schema_version")

    def __init__(
        self,
        received: int = 0,
        applied: int = 0,
        rejected: int = 0,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.received = received
        self.applied = applied
        self.rejected = rejected
        self.schema_version = schema_version


class StockImportSummary:
    """Итог приёма остатков из 1С (§18.2 ``POST stock/import``)."""

    __slots__ = ("received", "applied", "rejected", "schema_version")

    def __init__(
        self,
        received: int = 0,
        applied: int = 0,
        rejected: int = 0,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self.received = received
        self.applied = applied
        self.rejected = rejected
        self.schema_version = schema_version


__all__ = [
    "OrderExportRequest",
    "OrderExportResult",
    "OrderStatusRequest",
    "OrderStatusResult",
    "PriceImportSummary",
    "StockImportSummary",
]