"""Догрузка галерей товаров OptiBox Pro: недостающие фото из выгрузки keaz.ru → S3.

Запуск: docker compose exec api python -m app.scripts.keaz_gallery

Что делает (идемпотентно):
1. Читает выгрузку ``app/data/keaz_optibox_pro_export.json``: у каждого товара
   список ``photos`` (первый URL == ``image``). Если ключа ``photos`` нет —
   ожидается одно фото из ``image``.
2. Ищет товар в БД по ``sku``. Сверяет число записей ``ProductPhoto`` с
   ожидаемым: если фото уже достаточно — товар пропускается.
3. Иначе скачивает недостающий хвост (expected[count:]), заливает пары
   ``photos-product/{product_id}/{uuid8}.webp`` (+``_thumb.webp``) через
   ``_store_pair`` из ``app.scripts.keaz_photos`` и создаёт записи
   ``ProductPhoto`` (sort_order продолжает существующий порядок).

Вежливая пауза 0.15 с между запросами к files.keaz.ru. Наименования, цены
и характеристики не трогает.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid as uuid_mod
from pathlib import Path

from sqlalchemy import func, select

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Product, ProductPhoto
from app.scripts.keaz_photos import _fetch, _store_pair

log = get_logger("keaz_gallery")

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "keaz_optibox_pro_export.json"
POLLITE_SLEEP_SEC = 0.15
KEAZ_HOST = "https://files.keaz.ru"


def _abs_url(url: str) -> str:
    """В выгрузке встречаются относительные URL («/f/…/….mp4-preview.jpg»)."""
    if url.startswith("/"):
        return KEAZ_HOST + url
    return url


async def main() -> None:
    setup_logging()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    done = skipped = failed = missing = 0
    async with AsyncSessionLocal() as db:
        for item in data["products"]:
            sku = item["sku"]
            expected = item.get("photos") or ([item["image"]] if item.get("image") else [])
            product = (
                await db.execute(select(Product).where(Product.sku == sku))
            ).scalar_one_or_none()
            if product is None:
                missing += 1
                log.warning("product_not_found", sku=sku)
                continue

            rows = (
                await db.execute(
                    select(ProductPhoto)
                    .where(ProductPhoto.product_id == product.id)
                    .order_by(ProductPhoto.sort_order, ProductPhoto.created_at)
                )
            ).scalars().all()
            if len(rows) >= len(expected):
                skipped += 1
                continue

            uploaded = 0
            for i, url in enumerate(expected[len(rows):]):
                url = _abs_url(url)
                try:
                    stem = f"photos-product/{product.id}/{uuid_mod.uuid4().hex[:8]}"
                    key = _store_pair(_fetch(url), stem)
                except Exception as exc:  # noqa: BLE001 — скрипт: помечаем и идём дальше
                    failed += 1
                    log.warning("gallery_photo_failed", sku=sku, url=url[:60], error=str(exc))
                    continue
                db.add(ProductPhoto(product_id=product.id, photo_key=key, sort_order=len(rows) + i))
                uploaded += 1
                time.sleep(POLLITE_SLEEP_SEC)  # вежливо к files.keaz.ru
            await db.flush()
            if uploaded:
                done += 1
                log.info("gallery_done", sku=sku, added=uploaded, total=len(expected))
            else:
                skipped += 1

        await db.commit()
    log.info("keaz_gallery_done", total=len(data["products"]), done=done, skipped=skipped, failed=failed, missing=missing)


if __name__ == "__main__":
    asyncio.run(main())
