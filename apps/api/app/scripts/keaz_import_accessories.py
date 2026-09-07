"""Импорт недостающих товаров OptiBox Pro из экспорта keaz.ru (см. keaz_photos.py).

Запуск: docker compose exec api python -m app.scripts.keaz_import_accessories
Источник: app/data/keaz_optibox_pro_export.json (собран скриптом из /tmp/collect_keaz.py).

Что делает:
1. Создаёт серию «Аксессуары OptiBox Pro» (бренд KEAZ).
2. Добавляет недостающие товары: аксессуары (28) и корпус 382532 (страница 2
   листинга корпусов). Атрибуты = характеристики с keaz.ru (как есть,
   русские ключи) + model + photo_url.
3. Проставляет атрибут ``model`` всем товарам серии OptiBox Pro:
   «Щит распределительный» / «Щит мультимедиа» / «Аксессуары».
4. Новым товарам с фото — галерея ProductPhoto (webp 1200 + 400, как §16 п.17).

Цены НЕ трогает: base_price=0.00 — реальные цены заносятся импортом прайса.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Brand, Product, Series
from app.models.enums import StockStatus

log = get_logger("keaz_import")

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "keaz_optibox_pro_export.json"
ACC_SERIES_NAME = "Аксессуары OptiBox Pro"
CORPUS_SERIES_NAME = "OptiBox Pro"
BRAND_NAME = "KEAZ"


def _model_for(name: str) -> str:
    return "Щит мультимедиа" if "мультимедийн" in (name or "").lower() else "Щит распределительный"


async def main() -> None:
    setup_logging()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    async with AsyncSessionLocal() as db:
        brand = (
            await db.execute(select(Brand).where(Brand.name == BRAND_NAME))
        ).scalar_one_or_none()
        if brand is None:
            brand = Brand(name=BRAND_NAME)
            db.add(brand)
            await db.flush()

        acc_series = (
            await db.execute(select(Series).where(Series.name == ACC_SERIES_NAME))
        ).scalar_one_or_none()
        if acc_series is None:
            acc_series = Series(name=ACC_SERIES_NAME, brand_id=brand.id)
            db.add(acc_series)
            await db.flush()

        corpus_series = (
            await db.execute(select(Series).where(Series.name == CORPUS_SERIES_NAME))
        ).scalar_one()

        # существующие sku → обновление модели
        existing = {
            p.sku: p
            for p in (
                await db.execute(select(Product).where(Product.sku.in_([x["sku"] for x in data["products"]])))
            ).scalars().all()
        }

        created = photo_done = 0
        for item in data["products"]:
            sku = item["sku"]
            product = existing.get(sku)
            if product is None:
                is_acc = item["section"] == "Аксессуары"
                attributes = {"model": item["model"], **item["characteristics"], "photo_url": item["image"]}
                product = Product(
                    sku=sku,
                    name=item["name"],
                    brand_id=brand.id,
                    series_id=acc_series.id if is_acc else corpus_series.id,
                    base_price=Decimal("0.00"),
                    stock_status=StockStatus.IN_STOCK,
                    attributes=attributes,
                )
                db.add(product)
                await db.flush()
                created += 1
            else:
                # модель существующему — по purpose, если он есть, иначе по имени
                purpose = (product.attributes or {}).get("purpose", "")
                model = (
                    "Щит мультимедиа" if "ультимед" in purpose
                    else "Щит распределительный" if purpose
                    else _model_for(product.name)
                )
                product.attributes = {**(product.attributes or {}), "model": model}

        # фото новым товарам (без галереи)
        new_ids = [p.id for p in (await db.execute(select(Product))).scalars().all()
                   if p.sku not in existing]
        # простая проверка «есть ли фото» ленивым подсчётом по одному — товаров немного
        from sqlalchemy import func
        from app.models.catalog import ProductPhoto
        from app.services.storage import StorageError
        from app.scripts.keaz_photos import _store_pair, _fetch

        for pid in new_ids:
            product = (await db.execute(select(Product).where(Product.id == pid))).scalar_one()
            if not product.attributes or not product.attributes.get("photo_url"):
                continue
            have = await db.scalar(
                select(func.count()).select_from(ProductPhoto).where(ProductPhoto.product_id == pid)
            )
            if have:
                continue
            try:
                stem = f"photos-product/{pid}/{uuid_hex()}"
                key = _store_pair(_fetch(product.attributes["photo_url"]), stem)
            except StorageError as exc:
                log.warning("photo_failed", sku=product.sku, error=str(exc))
                continue
            db.add(ProductPhoto(product_id=pid, photo_key=key, sort_order=0))
            photo_done += 1

        await db.commit()
        log.info(
            "keaz_import_done",
            created=created,
            photos_added=photo_done,
            acc_series=ACC_SERIES_NAME,
        )


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


if __name__ == "__main__":
    asyncio.run(main())
