"""Jinja2-окружение для рендера уведомлений (§20.1).

Шаблоны лежат в ``app/templates/notifications/*.j2`` (локализация RU).
Текст уведомлений — НЕ HTML, поэтому autoescape отключён (вывод как есть).
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "notifications"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,         # текст уведомлений — не HTML
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_notification(template_name: str, **context) -> str:
    """Рендер Jinja2-шаблона уведомления (§20.1)."""
    return _env.get_template(template_name).render(**context)
