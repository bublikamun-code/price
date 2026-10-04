"""Заглушка клиента 1С — поведение по умолчанию (§18).

Почему заглушка, а не «одна строка ``None``»:

* **Приложение обязано стартовать** при любых настройках. Отсутствие 1С —
  нормальный режим стенда, а не повод падать на импорте.
* **Отказ должен быть явным и понятным.** Молчаливый ``None`` превращался бы
  в ``AttributeError: 'NoneType' object has no attribute ...`` где-нибудь в
  обработчике запроса — оператор не понял бы причину. Заглушка отвечает
  ``OneCNotConfiguredError`` с текстом «что задать в .env».
* **Контракт зафиксирован заранее.** Реализация одна (заглушка), но она уже
  подписана под ``OneCClient``: когда появится настоящий HTTP-клиент, вызов
  сайтов и роутера не изменятся.

Сеть не трогается ни при каком сценарии: в этом модуле нет ни одного сетевого
импорта — «не настроено» означает «ни одного TCP-соединения».
"""
from __future__ import annotations

from app.integrations.one_c.errors import NOT_CONFIGURED_HINT, OneCNotConfiguredError
from app.integrations.one_c.schemas import (
    OrderExportRequest,
    OrderExportResult,
    OrderStatusRequest,
    OrderStatusResult,
)

#: Сообщение об отказе. action подставляется — видно, какая именно операция.
NOT_CONFIGURED_MESSAGE = (
    "Интеграция с 1С не настроена: {reason}. "
    "Операция «{action}» не выполнена. {hint}"
)


def default_reason() -> str:
    """Причина по умолчанию, если конкретную причину не передали."""
    return (
        "не заданы INTEGRATION_1C_ENABLED=true и INTEGRATION_1C_BASE_URL "
        "либо INTEGRATION_1C_ENABLED=false"
    )


class StubOneCClient:
    """Клиент-заглушка: честно отказывает, ничего не отправляя.

    Экземпляр безопасен для создания где угодно и в любом числе: состояния
    нет, сетевых ресурсов нет, только неизменяемая причина отказа.
    """

    transport = "stub"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or default_reason()

    @property
    def configured(self) -> bool:
        """Заглушка никогда не настроена — это её суть."""
        return False

    def describe(self) -> str:
        """Строка для логов и /healthz-подобной диагностики."""
        return f"OneCClient[stub]: {self.reason}"

    async def export_orders(self, request: OrderExportRequest) -> OrderExportResult:
        raise self._reject("выгрузка заказов в 1С")

    async def push_order_status(self, request: OrderStatusRequest) -> OrderStatusResult:
        raise self._reject("возврат статуса заказа в 1С")

    async def aclose(self) -> None:
        """Закрывать нечего — соединений нет."""
        return None

    def _reject(self, action: str) -> OneCNotConfiguredError:
        return OneCNotConfiguredError(
            NOT_CONFIGURED_MESSAGE.format(
                reason=self.reason,
                action=action,
                hint=NOT_CONFIGURED_HINT,
            )
        )


__all__ = ["NOT_CONFIGURED_MESSAGE", "StubOneCClient", "default_reason"]