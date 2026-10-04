"""Ошибки интеграции с 1С и их маппинг в HTTP (§18).

Каждое исключение уже содержит русское сообщение, готовое к показу оператору,
и код, по которому HTTP-слой формирует ответ. Клиент 1С наружу не отдаёт
свои исключения — роутер превращает их в код ответа.
"""
from __future__ import annotations

NOT_CONFIGURED_HINT = (
    "Задайте INTEGRATION_1C_ENABLED=true и INTEGRATION_1C_BASE_URL "
    "(см. .env.example), затем перезапустите api. Контракт обмена: "
    "ARCHITECTURE_PLAN.md §18."
)


class OneCError(Exception):
    """Базовая ошибка обмена с 1С."""

    #: Человекочитаемый код для клиента 1С и для метрик.
    code = "ONE_C_ERROR"
    #: HTTP-статус, которым ошибка отвечает наружу.
    http_status = 502


class OneCNotConfiguredError(OneCError):
    """Интеграция не настроена: нет настроек либо включена заглушка.

    Отдельный тип, а не подвид «транспорта»: это не сбой 1С и не наша ошибка —
    состояние стенда. Оператору нужен конкретный текст «что задать».
    """

    code = "ONE_C_NOT_CONFIGURED"
    http_status = 503


class OneCTransportError(OneCError):
    """1С недоступна: таймаут, обрыв соединения, сетевая ошибка."""

    code = "ONE_C_TRANSPORT_ERROR"
    http_status = 502


class OneCAuthError(OneCError):
    """1С отклонила наш токен (401/403 на исходящем вызове)."""

    code = "ONE_C_AUTH_ERROR"
    http_status = 502


class OneCResponseError(OneCError):
    """1С ответила кодом ошибки или телом, которого мы не понимаем."""

    code = "ONE_C_RESPONSE_ERROR"
    http_status = 502