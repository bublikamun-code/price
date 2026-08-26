"""Jinja2-окружения для рендера шаблонов.

* Уведомления (§20.1): ``app/templates/notifications/*.j2``, текст (не HTML),
  autoescape отключён.
* PDF (§16 п.25): ``app/templates/pdf/*.j2`` — HTML, поэтому autoescape
  включён; рендерится в Celery-воркере через weasyprint.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "notifications"
_PDF_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "pdf"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,         # nosec B701 — текст уведомлений уходит в JSON/SSE и Telegram, не в HTML;
                              # экранирование исказило бы текст (& → &amp;). PDF-окружение ниже — с autoescape=True.
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_notification(template_name: str, **context) -> str:
    """Рендер Jinja2-шаблона уведомления (§20.1)."""
    return _env.get_template(template_name).render(**context)


@lru_cache(maxsize=1)
def get_pdf_env() -> Environment:
    """Jinja2-окружение для PDF-шаблонов (HTML → weasyprint, §16 п.25).

    Отдельное окружение: autoescape=True (в отличие от уведомлений) —
    пользовательские данные (наименования, реквизиты) экранируются.
    ``lru_cache`` — синглтон, чтобы не парсить шаблоны на каждый рендер.
    """
    return Environment(
        loader=FileSystemLoader(str(_PDF_TEMPLATES_DIR)),
        autoescape=True,          # PDF — HTML-документ
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_pdf(template_name: str, **context) -> str:
    """Рендер HTML PDF-шаблона (готов к передаче в weasyprint)."""
    return get_pdf_env().get_template(template_name).render(**context)
