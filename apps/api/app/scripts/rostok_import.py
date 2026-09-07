"""Импорт товаров Rostok (rostok_products.json) — серии по разделам каталога.

Запуск: docker compose exec api python -m app.scripts.sw_import

1. Бренд SmartWatt; серия по значению «Серия» из характеристик (AVR *).
2. Товары: attributes = {model: типология, description, photo_url, характеристики}.
3. Галерея: photos[] → photos-product/{id}/{uuid8}.webp (ProductPhoto).
4. KEAZ: карточкам корпусов — составное описание из реальных характеристик.
"""
from __future__ import annotations

import asyncio
import json
import uuid as uuid_mod
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Brand, Product, ProductPhoto, Series
from app.models.enums import StockStatus
from app.services.storage import StorageError, put_bytes

log = get_logger("rostok_import")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
SW_FILE = Path(__file__).resolve().parents[1] / "data" / "rostok_products.json"


def _fetch(url: str) -> bytes:
    resp = httpx.get(url, headers=UA, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _to_webp(data: bytes, size: tuple[int, int]) -> bytes:
    """Прозрачный PNG/JPG композитим на БЕЛЫЙ фон: convert("RGB") без маски
    превращает прозрачные пиксели в чёрные (баг чёрного фона у витрины)."""
    img = Image.open(BytesIO(data))
    if img.mode != "RGB":
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        img = bg
    img = ImageOps.fit(img, size, method=Image.LANCZOS)
    out = BytesIO()
    img.save(out, "WEBP", quality=82)
    return out.getvalue()


async def import_rostok(db) -> dict:
    data = json.loads(SW_FILE.read_text(encoding="utf-8"))
    brand = (
        await db.execute(select(Brand).where(Brand.name == "Rostok"))
    ).scalar_one_or_none()
    if brand is None:
        brand = Brand(name="Rostok", slug="rostok")
        db.add(brand)
        await db.flush()

    series_cache: dict[str, Series] = {}
    created = photos = 0
    existing_skus = set(
        (await db.execute(select(Product.sku))).scalars().all()
    )
    for item in data["products"]:
        if item["sku"] in existing_skus:
            continue
        series_name = item["characteristics"].get("Серия", "Rostok")
        series = series_cache.get(series_name)
        if series is None:
            series = (
                await db.execute(select(Series).where(Series.name == series_name))
            ).scalar_one_or_none()
            if series is None:
                series = Series(name=series_name, brand_id=brand.id)
                db.add(series)
                await db.flush()
            series_cache[series_name] = series

        attributes = {
            "typology": item.get("typology", ""),
            "description": item.get("description", ""),
            "photo_url": item.get("image", ""),
            **item["characteristics"],
        }
        product = Product(
            sku=item["sku"],
            name=item["name"],
            brand_id=brand.id,
            series_id=series.id,
            base_price=Decimal("0.00"),
            stock_status=StockStatus.IN_STOCK,
            attributes=attributes,
        )
        db.add(product)
        await db.flush()
        created += 1

        # галерея (до 8 фото на товар)
        for i, url in enumerate(item.get("photos", [])[:8]):
            try:
                stem = f"photos-product/{product.id}/{uuid_mod.uuid4().hex[:8]}"
                put_bytes(settings.s3_bucket_photos, f"{stem}.webp", _to_webp(_fetch(url), (1200, 1200)), content_type="image/webp")
                db.add(ProductPhoto(product_id=product.id, photo_key=f"{stem}.webp", sort_order=i))
                photos += 1
                await asyncio.sleep(0.1)
            except (StorageError, httpx.HTTPError) as exc:
                log.warning("sw.photo_failed", sku=item["sku"], url=url[:60], error=str(exc))
                break

    await db.commit()
    return {"created": created, "photos": photos}


async def main() -> None:
    setup_logging()
    async with AsyncSessionLocal() as db:
        res = await import_rostok(db)
    log.info("rostok_import_done", **res)


if __name__ == "__main__":
    asyncio.run(main())
