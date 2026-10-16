"""Общий рендер HTML → PDF (weasyprint, §16 п.25).

Шрифт DejaVu Sans лежит в репозитории (``app/assets/fonts``) и подключается
через ``@font-face``: ни прод-хост (PM2 без Docker, только URW base35), ни
лёгкие контейнеры не гарантируют системный шрифт с кириллицей. Без этого
Pango сваливается на fallback без русских глифов, и весь кириллический
текст в PDF становится чёрными плашками (баг счёта СЧ-2026-000002).
"""
from __future__ import annotations

from pathlib import Path

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_FONT_FACE_CSS = f"""
@font-face {{
    font-family: "DejaVu Sans";
    src: url("file://{_FONTS_DIR / 'DejaVuSans.ttf'}");
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: "DejaVu Sans";
    src: url("file://{_FONTS_DIR / 'DejaVuSans-Bold.ttf'}");
    font-weight: bold;
    font-style: normal;
}}
"""


def write_pdf(html: str) -> bytes:
    """HTML из ``app/templates/pdf/*.j2`` → байты PDF со встроенным шрифтом."""
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration

    font_config = FontConfiguration()
    font_css = CSS(string=_FONT_FACE_CSS, font_config=font_config)
    return HTML(string=html).write_pdf(font_config=font_config, stylesheets=[font_css])


__all__ = ["write_pdf"]
