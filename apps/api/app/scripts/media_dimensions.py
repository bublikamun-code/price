"""Пересчёт фактических размеров изображений в реестре медиа (§16 п.37).

Запуск: docker compose exec api python -m app.scripts.media_dimensions

Зачем: размеры в ``media_assets`` писались по конвенции загрузчика (бокс
1200×1200 / 400×400), а реальный кадр может быть 800×600 — загрузчик вписывает
фото в бокс без кропа и без увеличения. Клиент кэширует картинку по стабильному
id и рисует её по этим размерам, поэтому в реестре нужны настоящие числа.

Скрипт идемпотентен: перезаписывает ТОЛЬКО ``width``/``height`` и только там,
где фактический размер отличается от записанного. Остальные поля строки и
состав реестра не трогаются — повторный прогон ничего не меняет.

Объекты, которых нет в бакете (удалённые фото), пропускаются: их размеры
остаются конвенционными, а не выдуманными.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.file import MediaAsset
from app.services import media as media_service

log = get_logger("app.scripts.media_dimensions")


async def recompute_dimensions(db, *, dry_run: bool = False) -> dict[str, int]:
    """Пересчитать размеры строк реестра по фактическим размерам объектов.

    Возвращает статистику: сколько обновлено, сколько совпало, сколько
    пропущено (объект недоступен).
    """
    stats = {"total": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    rows = (
        await db.execute(select(MediaAsset).order_by(MediaAsset.id))
    ).scalars().all()
    for row in rows:
        stats["total"] += 1
        size = await media_service.probe_dimensions(row.s3_key)
        if size is None:
            stats["skipped"] += 1
            continue
        if (row.width, row.height) == size:
            stats["unchanged"] += 1
            continue
        if dry_run:
            stats["updated"] += 1
            continue
        row.width, row.height = size
        stats["updated"] += 1
    if not dry_run:
        await db.commit()
    return stats


async def main(dry_run: bool = False) -> None:
    setup_logging()
    async with AsyncSessionLocal() as db:
        stats = await recompute_dimensions(db, dry_run=dry_run)
    log.info("media_dimensions.done", **stats)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Пересчёт фактических размеров в реестре медиа"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только показать, что изменится, без записи в БД",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
