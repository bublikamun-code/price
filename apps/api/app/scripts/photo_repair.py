"""Перезаливка фото товаров из исходников с БЕЛЫМ композитом (фикс чёрного фона).

Запуск: docker compose exec api python -m app.scripts.photo_repair

Ключи S3 остаются прежними — перезаписываются только файлы. Пары «фото в БД →
исходный URL» берутся из JSON выгрузок (порядок photos ↔ sort_order).
KEAZ: у корпусов/аксессуаров по одному фото — attributes.photo_url / выгрузка.

После обработки каждый файл проверяется на «залитый чёрный» (доля тёмных
пикселей) — если источник сам с чёрным фоном, товар попадает в отчёт.
"""
from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Product, ProductPhoto
from app.services.storage import StorageError, put_bytes
from app.scripts.keaz_photos import _to_webp

log = get_logger("photo_repair")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DATA = Path(__file__).resolve().parents[1] / "data"
SOURCES = [
    DATA / "keaz_optibox_pro_export.json",
    DATA / "smartwatt_products.json",
    DATA / "rostok_products.json",
]
POLLITE_SLEEP_SEC = 0.12


def _dark_fraction(img: Image.Image) -> float:
    """Доля почти чёрных пикселей (после композита — детект «залитого» фона)."""
    gray = img.convert("L")
    hist = gray.histogram()
    dark = sum(hist[:12])
    return dark / (img.size[0] * img.size[1])


async def main() -> None:
    setup_logging()
    sources: dict[str, list[str]] = {}

    for path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["products"]:
            main_url = item.get("image")
            rest = [u for u in item.get("photos", []) if u != main_url]
            sources[item["sku"]] = ([main_url] if main_url else []) + rest

    repaired = failed = 0
    dark_report: list[str] = []

    async with AsyncSessionLocal() as db:
        products = (
            await db.execute(select(Product))
        ).scalars().all()
        for product in products:
            urls = sources.get(product.sku, [])
            if not urls:
                continue
            rows = (
                await db.execute(
                    select(ProductPhoto)
                    .where(ProductPhoto.product_id == product.id)
                    .order_by(ProductPhoto.sort_order, ProductPhoto.created_at)
                )
            ).scalars().all()
            for row, url in zip(rows, urls):
                try:
                    raw = httpx.get(url, headers=UA, timeout=30.0, follow_redirects=True).content
                    webp = _to_webp(raw, (1200, 1200))
                    if _dark_fraction(Image.open(BytesIO(webp))) > 0.35:
                        dark_report.append(f"{product.sku}: {row.photo_key}")
                    put_bytes(settings.s3_bucket_photos, row.photo_key, webp, content_type="image/webp")
                    repaired += 1
                except (StorageError, httpx.HTTPError) as exc:
                    failed += 1
                    log.warning("repair.failed", sku=product.sku, url=url[:60], error=str(exc))
                await asyncio.sleep(POLLITE_SLEEP_SEC)

    log.info(
        "photo_repair_done",
        repaired=repaired,
        failed=failed,
        still_dark=dark_report,
    )


if __name__ == "__main__":
    asyncio.run(main())
