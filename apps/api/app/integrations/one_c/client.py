"""Протокол клиента 1С — контракт исходящего обмена портал → 1С (§18.2).

Протокол (``typing.Protocol``), а не ABC: реализации подставляются фабрикой
``app.integrations.one_c.factory``, и структурная типизация позволяет проверять
их совместимость без наследования.

Контракт методов соответствует двум исходящим эндпоинтам §18.2:
  * ``export_orders``     — ``GET  /api/integrations/1c/orders/export``;
  * ``push_order_status`` — ``POST /api/integrations/1c/orders/status``.

Входящие ``prices/import`` и ``stock/import`` клиентом не покрыты: там 1С
сама присылает документы, а портал принимает их сервисом импорта.

Гарантии реализаций:
  * любой метод либо возвращает результат, либо бросает подкласс
    ``OneCError`` — вызывающая сторона всегда знает, что делать (§18);
  * ``configured`` показывает, поедет ли обмен в принципе: у заглушки всегда
    ``False``, у HTTP-клиента — ``True``.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.integrations.one_c.schemas import (
    OrderExportRequest,
    OrderExportResult,
    OrderStatusRequest,
    OrderStatusResult,
)


@runtime_checkable
class OneCClient(Protocol):
    """Клиент 1С: исходящий обмен портал → 1С."""

    #: Короткое имя транспорта для логов и диагностики: "http" | "stub".
    transport: str

    @property
    def configured(self) -> bool:
        """Готова ли интеграция к реальному обмену."""
        ...

    async def export_orders(self, request: OrderExportRequest) -> OrderExportResult:
        """Выгрузить заказы, изменённые после ``request.since``."""
        ...

    async def push_order_status(self, request: OrderStatusRequest) -> OrderStatusResult:
        """Вернуть в 1С новый статус заказа."""
        ...

    async def aclose(self) -> None:
        """Освободить ресурсы (соединения). Вызывается при остановке приложения."""
        ...


__all__ = ["OneCClient"]