"""Фабрика выбора реализации клиента 1С по настройкам (§18).

Правило одно и явное:

    настроено (INTEGRATION_1C_ENABLED=true + INTEGRATION_1C_BASE_URL)
        → HttpOneCClient с таймаутом из настроек;
    иначе
        → StubOneCClient с причиной «что именно не задано».

Фабрика **не бросает исключений** — это требование старта приложения
(«приложение обязано стартовать и в любом случае»). Любая неожиданность при
построении HTTP-клиента логируется и деградирует до заглушки: неверный
``BASE_URL`` должен приводить к понятному 503 на 1С-эндпоинтах, а не к
``Traceback`` при импорте ``app.main``.

``get_one_c_client()`` кэширует клиента на процесс: httpx-клиент держит
пул соединений, создавать его на каждый запрос незачем.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.one_c.client import OneCClient
from app.integrations.one_c.http_client import HttpOneCClient
from app.integrations.one_c.stub import StubOneCClient

log = get_logger("app.integrations.one_c.factory")


class _OneCConfig(Protocol):
    """Минимум настроек, нужный фабрике (тесты подставляют такой объект)."""

    integration_1c_enabled: bool
    integration_1c_base_url: str
    integration_1c_timeout_sec: float
    integration_1c_token: str


def missing_outbound_settings(config: _OneCConfig) -> list[str]:
    """Список настроек исходящего обмена, которых не хватает (для сообщения)."""
    missing: list[str] = []
    if not config.integration_1c_enabled:
        missing.append("INTEGRATION_1C_ENABLED=true")
    if not config.integration_1c_base_url.strip():
        missing.append("INTEGRATION_1C_BASE_URL")
    return missing


def describe_one_c_state(config: _OneCConfig) -> str:
    """Человекочитаемое описание состояния интеграции — для логов и заглушки."""
    missing = missing_outbound_settings(config)
    if not missing:
        return (
            f"настроено (INTEGRATION_1C_BASE_URL={config.integration_1c_base_url}, "
            f"таймаут {config.integration_1c_timeout_sec} с)"
        )
    if len(missing) == 2:
        return "не заданы INTEGRATION_1C_ENABLED=true и INTEGRATION_1C_BASE_URL"
    return f"не задано {missing[0]}"


def create_one_c_client(config: _OneCConfig | None = None) -> OneCClient:
    """Собрать клиента 1С по настройкам. Всегда возвращает рабочий объект."""
    cfg = config if config is not None else settings
    try:
        missing = missing_outbound_settings(cfg)
        if missing:
            reason = describe_one_c_state(cfg)
            log.info("one_c.stub_selected", reason=reason)
            return StubOneCClient(reason=reason)
        client = HttpOneCClient(
            base_url=cfg.integration_1c_base_url,
            token=cfg.integration_1c_token,
            timeout_sec=cfg.integration_1c_timeout_sec,
        )
        log.info("one_c.http_client_selected", client=client.describe())
        return client
    except Exception as exc:  # защитный контур: старт важнее интеграции
        log.error("one_c.client_build_failed", error=str(exc))
        return StubOneCClient(reason=f"не удалось построить клиент 1С: {exc}")


@lru_cache(maxsize=1)
def get_one_c_client() -> OneCClient:
    """Клиент 1С на весь процесс (ленивая инициализация при первом обращении)."""
    return create_one_c_client(settings)


def reset_one_c_client() -> None:
    """Сбросить кэш клиента (тесты, перезагрузка настроек)."""
    get_one_c_client.cache_clear()


__all__ = [
    "create_one_c_client",
    "describe_one_c_state",
    "get_one_c_client",
    "missing_outbound_settings",
    "reset_one_c_client",
]