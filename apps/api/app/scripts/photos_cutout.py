"""Вырезание фона у фото товаров (прозрачность) — замена белого композита.

Запуск: docker compose exec api python -m app.scripts.photos_cutout

Что делает:
1. Собирает «sku → список URL исходников» из трёх JSON-выгрузок
   (data/keaz_optibox_pro_export.json, rostok_products.json,
   smartwatt_products.json). Порядок photos[] соответствует sort_order
   записей ProductPhoto (первый URL == image, как в photo_repair.py).
2. Для каждого товара сопоставляет существующие ProductPhoto
   (ORDER BY sort_order, created_at) с URL по индексу.
3. Каждую пару обрабатывает: скачивает URL (httpx, UA как в keaz_photos.py,
   timeout 30), вырезает фон rembg (модель u2net, сессия создаётся ОДИН раз
   на весь прогон — иначе remove() может зависнуть), ресайзит и перезаписывает
   в S3 ОБА объекта: photo_key (large 1200×1200) и thumb (400×400) — ключ
   БД не меняется, записи БД не трогаются. Прозрачность СОХРАНЯЕТСЯ
   (RGBA webp q82, без белого композита — замена поведения _to_webp).

Требование: модель u2net должна быть скачана в контейнере —
~/.u2net/u2net.onnx (new_session('u2net') при отсутствии сети упадёт).

Идемпотентность не требуется (файлы просто перезаписываются), скрипт можно
перезапускать — например для докачи после обрыва сети: уже вырезанные фото
(RGBA с прозрачностью в S3) пропускаются. Прогресс логируется
каждые 25 фото; ошибки скачивания/обработки — warning и дальше, в конце
сводка done/failed по брендам. Расчётное время полного прогона — порядка
нескольких часов на dev-CPU (rembg ~5–10 с на фото) — запускать удобно
через nohup/фон.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from rembg import new_session, remove
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import Product, ProductPhoto
from app.services.storage import StorageError, get_bytes, put_bytes

log = get_logger("photos_cutout")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DATA = Path(__file__).resolve().parents[1] / "data"
SOURCES = [
    ("KEAZ", DATA / "keaz_optibox_pro_export.json"),
    ("Rostok", DATA / "rostok_products.json"),
    ("SmartWatt", DATA / "smartwatt_products.json"),
]
POLLITE_SLEEP_SEC = 0.12
PROGRESS_EVERY = 25

SESSION = new_session("u2net")


def _cutout_rgba(data: bytes) -> Image.Image:
    """rembg (одна инференс на фото) → RGBA PIL-изображение.

    До инференса даунскейл до 1600 px: u2net всё равно считает маску на
    320×320 и апсемплит её — на качестве почти не сказывается, а пиковая
    память numpy/rembg падает в разы (без даунскейла большие исходники
    убивали контейнер по OOM при лимите ~3.8 ГБ).
    """
    img = Image.open(BytesIO(data))
    img.thumbnail((1600, 1600), Image.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    cut = remove(img, session=SESSION)  # RGBA
    return cut.convert("RGBA")


def _fit_webp(img: Image.Image, size: tuple[int, int]) -> bytes:
    """RGBA → fit size (LANCZOS, альфа сохраняется) → webp q82."""
    fitted = ImageOps.fit(img, size, method=Image.LANCZOS)
    out = BytesIO()
    fitted.save(out, "WEBP", quality=82)
    return out.getvalue()


def _thumb_key(photo_key: str) -> str:
    """photos-product/{id}/{uuid8}.webp → …/{uuid8}_thumb.webp."""
    return photo_key[: -len(".webp")] + "_thumb.webp"


def _already_cutout(photo_key: str) -> bool:
    """True, если large-объект в S3 уже RGBA с прозрачными пикселями.

    Позволяет перезапускать скрипт без повторной обработки: обрезок у
    прогона нет (пара large+thumb пишется атомарно по очереди), поэтому
    RGBA у large означает, что и thumb уже вырезан.
    """
    try:
        data = get_bytes(settings.s3_bucket_photos, photo_key)
        img = Image.open(BytesIO(data))
        if img.mode != "RGBA":
            return False
        hist = img.getchannel("A").histogram()
        return sum(hist[:16]) / (img.size[0] * img.size[1]) > 0.02
    except (StorageError, Exception):  # noqa: BLE001 — нет объекта/битый файл → обрабатываем
        return False


def _abs_url(url: str | None) -> str | None:
    """Относительные URL KEAZ (/f/...) → https://files.keaz.ru/f/...."""
    if url and url.startswith("/"):
        return "https://files.keaz.ru" + url
    return url


async def main() -> None:
    setup_logging()
    start = time.monotonic()
    # Ограничение фото на один запуск процесса: onnxruntime/numpy заметно
    # копят память внутри процесса, при долгом прогоне контейнер уходит в
    # OOM. Запускать чанками: PHOTOS_CUTOUT_MAX_NEW=40 в цикле, пока
    # прогон не выйдет с done=0 (всё обработано или failed).
    max_new = int(os.environ.get("PHOTOS_CUTOUT_MAX_NEW", "0"))

    sources: dict[str, list[str]] = {}
    for name, path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["products"]:
            main_url = _abs_url(item.get("image"))
            rest = [_abs_url(u) for u in item.get("photos", []) if u != item.get("image")]
            sources[item["sku"]] = ([main_url] if main_url else []) + rest

    stats: dict[str, dict[str, int]] = {
        name: {"done": 0, "failed": 0} for name, _ in SOURCES
    }
    sku_brand: dict[str, str] = {}
    for name, path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["products"]:
            sku_brand[item["sku"]] = name

    processed = 0
    new_done = 0
    chunk_limit = False
    async with AsyncSessionLocal() as db:
        products = (await db.execute(select(Product))).scalars().all()
        for product in products:
            if chunk_limit:
                break
            urls = sources.get(product.sku, [])
            if not urls:
                continue
            brand = sku_brand.get(product.sku, "?")
            rows = (
                await db.execute(
                    select(ProductPhoto)
                    .where(ProductPhoto.product_id == product.id)
                    .order_by(ProductPhoto.sort_order, ProductPhoto.created_at)
                )
            ).scalars().all()
            for row, url in zip(rows, urls):
                if _already_cutout(row.photo_key):
                    stats[brand]["skipped"] = stats[brand].get("skipped", 0) + 1
                    processed += 1
                    continue
                try:
                    raw = httpx.get(url, headers=UA, timeout=30.0, follow_redirects=True).content
                    rgba = _cutout_rgba(raw)  # одна инференс на фото
                    put_bytes(settings.s3_bucket_photos, row.photo_key, _fit_webp(rgba, (1200, 1200)), content_type="image/webp")
                    put_bytes(settings.s3_bucket_photos, _thumb_key(row.photo_key), _fit_webp(rgba, (400, 400)), content_type="image/webp")
                    stats[brand]["done"] += 1
                    new_done += 1
                    if max_new and new_done >= max_new:
                        chunk_limit = True
                        break
                except Exception as exc:  # noqa: BLE001 — скрипт: warning и дальше
                    stats[brand]["failed"] += 1
                    log.warning("cutout.failed", brand=brand, sku=product.sku, url=url[:60], error=str(exc))
                processed += 1
                if processed % PROGRESS_EVERY == 0:
                    log.info(
                        "cutout.progress",
                        processed=processed,
                        elapsed_sec=round(time.monotonic() - start, 1),
                        stats=stats,
                    )
                await asyncio.sleep(POLLITE_SLEEP_SEC)

    log.info(
        "photos_cutout_done",
        processed=processed,
        new_done=new_done,
        chunk_limit=chunk_limit,
        elapsed_sec=round(time.monotonic() - start, 1),
        stats=stats,
    )


if __name__ == "__main__":
    asyncio.run(main())
