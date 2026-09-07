"""Фото серии OptiBox Pro: скачивание с оригинального сайта KEAZ → S3.

Запуск: docker compose exec api python -m app.scripts.keaz_photos

Что делает (идемпотентно):
1. ``series.photo_key`` (внешний URL keaz.ru) → обрабатывает в webp и заливает
   в S3 ``photos-series/optibox-pro.webp`` + ``_thumb.webp`` (§16 п.17),
   затем обновляет ``series.photo_key`` на S3-ключ — витрина и бренд-страница
   перестают зависеть от внешнего хостинга.
2. Каждому товару серии с ``attributes->>'photo_url'`` скачивает личное фото
   и кладёт в галерею ``photos-product/{product_id}/{uuid8}.webp`` (+_thumb),
   создавая запись ``ProductPhoto`` (sort_order=0). Товары с уже заполненной
   галереей пропускаются.

Наименования и характеристики не трогает (сверены с keaz.ru — совпадают).
"""
from __future__ import annotations

import asyncio
import time
import uuid as uuid_mod
from io import BytesIO

import httpx
from PIL import Image, ImageOps
from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Product, ProductPhoto, Series
from app.services.storage import put_bytes

log = get_logger("keaz_photos")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
SERIES_NAME = "%optibox%"
SERIES_KEY_STEM = "photos-series/optibox-pro"
POLLITE_SLEEP_SEC = 0.15


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


def _store_pair(data: bytes, key_stem: str) -> str:
    """large 1200×1200 + thumb 400×400 → S3; возвращает ключ large."""
    put_bytes(settings.s3_bucket_photos, f"{key_stem}.webp", _to_webp(data, (1200, 1200)), content_type="image/webp")
    put_bytes(settings.s3_bucket_photos, f"{key_stem}_thumb.webp", _to_webp(data, (400, 400)), content_type="image/webp")
    return f"{key_stem}.webp"


async def main() -> None:
    setup_logging()

    async with AsyncSessionLocal() as db:
        series = (
            await db.execute(select(Series).where(Series.name.ilike(SERIES_NAME)))
        ).scalar_one_or_none()
        if series is None:
            log.error("series_not_found", name=SERIES_NAME)
            return

        # 1) Фото серии → S3
        series_src = series.photo_key or ""
        if series_src.startswith("http"):
            key = _store_pair(_fetch(series_src), SERIES_KEY_STEM)
            series.photo_key = key
            log.info("series_photo_uploaded", key=key, src=series_src)
        else:
            log.info("series_photo_already_local", key=series_src)

        # 2) Личные фото товаров
        products = (
            await db.execute(select(Product).where(Product.series_id == series.id).order_by(Product.sku))
        ).scalars().all()

        done = skipped = failed = 0
        for product in products:
            have = await db.scalar(
                select(func.count()).select_from(ProductPhoto).where(ProductPhoto.product_id == product.id)
            )
            if have:
                skipped += 1
                continue
            url = (product.attributes or {}).get("photo_url")
            if not url:
                failed += 1
                log.warning("product_no_photo_url", sku=product.sku)
                continue
            try:
                stem = f"photos-product/{product.id}/{uuid_mod.uuid4().hex[:8]}"
                key = _store_pair(_fetch(url), stem)
            except Exception as exc:  # noqa: BLE001 — скрипт: помечаем и идём дальше
                failed += 1
                log.warning("product_photo_failed", sku=product.sku, error=str(exc))
                continue
            db.add(ProductPhoto(product_id=product.id, photo_key=key, sort_order=0))
            done += 1
            time.sleep(POLLITE_SLEEP_SEC)  # вежливо к files.keaz.ru

        await db.commit()
        log.info("keaz_photos_done", total=len(products), uploaded=done, skipped=skipped, failed=failed)


if __name__ == "__main__":
    asyncio.run(main())
