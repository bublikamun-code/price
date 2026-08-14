"""Структурированное логирование (structlog) → JSON.

Correlation ID пробрасывается через middleware (см. main.py).
См. ARCHITECTURE_PLAN.md §12.
"""
import logging
import sys

import structlog

from app.core.config import settings


def setup_logging() -> None:
    """Инициализация structlog. Вызывается один раз при старте приложения."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.env == "prod":
        processors.append(structlog.processors.JSONRenderer())
    else:
        # dev: цветной человек-читаемый вывод
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Перехват стандартного logging (uvicorn/sqlalchemy/alembic)
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
