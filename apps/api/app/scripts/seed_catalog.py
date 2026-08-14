"""Seed каталога: загрузка OptiBox Pro из Bitrix-выгрузки в БД.

Запуск: make seed-catalog  (в контейнере api: python -m app.scripts.seed_catalog)

Источник: ``app/data/OptiBox_Pro_Belarus.xlsx`` (экспорт 1С-Битрикс).
Idempotent: безопасен к повторному запуску (бренд/серия — get_or_create,
товары — upsert по sku). При каждом запуске создаётся новая запись
``PriceListVersion`` (как при реальном импорте).

ВНИМАНИЕ:
- Цены ТЕСТОВЫЕ (формула в app.importers.optibox) — заменить реальным
  импортом прайса (Этап 4).
- ``series.photo_key`` временно хранит внешний URL keaz.ru (до интеграции S3).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from app.importers.optibox import row_to_product
from sqlalchemy import select

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.models.catalog import PriceListVersion
from app.models.enums import (
    ImportMode,
    PriceListVersionStatus,
    StockStatus,
    UserRole,
)
from app.models.user import User
from app.repositories import catalog as repo

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "OptiBox_Pro_Belarus.xlsx"


def _read_rows(path: Path) -> list[dict]:
    """Прочитать лист «OptiBox Pro» → список dict (ключи = коды колонок)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["OptiBox Pro"]
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(h) for h in next(rows_iter)]
    out = []
    for raw in rows_iter:
        if raw is None or all(v is None for v in raw):
            continue
        out.append({header[i]: raw[i] for i in range(len(header))})
    wb.close()
    return out


async def seed_catalog() -> None:
    setup_logging()
    log = get_logger("app.scripts.seed_catalog")

    if not DATA_FILE.exists():
        msg = f"Файл данных не найден: {DATA_FILE}"
        print(f"❌ {msg}", file=sys.stderr)
        raise SystemExit(1)

    rows = _read_rows(DATA_FILE)
    log.info("seed.catalog.rows_read", count=len(rows))
    if not rows:
        print("⚠️  Нет строк для загрузки — файл пуст.", file=sys.stderr)
        return

    async with AsyncSessionLocal() as db:
        # Кем загружено: первый менеджер (роль MANAGER). Иначе — без версии.
        manager = await db.scalar(select(User).where(User.role == UserRole.MANAGER))
        version = None
        if manager is not None:
            version = PriceListVersion(
                uploaded_by=manager.id,
                filename=DATA_FILE.name,
                import_mode=ImportMode.UPSERT,
                status=PriceListVersionStatus.PROCESSING,
                rows_total=len(rows),
                base_currency="BYN",
                rate_to_byn=1,
                rate_source="SEED",
                started_at=datetime.now(timezone.utc),
            )
            db.add(version)
            await db.flush()
        else:
            log.warning("seed.catalog.no_manager", msg="PriceListVersion не создан")

        # Нормализуем все строки заранее (нужен photo_url первой для серии).
        products = [row_to_product(r) for r in rows]
        first_photo = next((p["photo_url"] for p in products if p["photo_url"]), None)

        brand = await repo.get_or_create_brand(db, name=products[0]["brand"])
        series = await repo.get_or_create_series(
            db,
            name=products[0]["series"],
            brand_id=brand.id,
            # DEV: внешний URL до интеграции S3 (Этап 4).
            photo_key=first_photo,
        )

        created = updated = errors = 0
        for p in products:
            try:
                _, is_new = await repo.upsert_product(
                    db,
                    sku=p["sku"],
                    name=p["name"],
                    brand_id=brand.id,
                    series_id=series.id,
                    base_price=p["base_price"],
                    attributes=p["attributes"],
                    stock_status=StockStatus.IN_STOCK,
                    price_list_version_id=version.id if version else None,
                )
                created += int(is_new)
                updated += int(not is_new)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.error("seed.catalog.row_error", sku=p.get("sku"), error=str(exc))

        if version is not None:
            version.rows_ok = created + updated
            version.rows_error = errors
            version.status = (
                PriceListVersionStatus.DONE if errors == 0 else PriceListVersionStatus.FAILED
            )
            version.finished_at = datetime.now(timezone.utc)

        await db.commit()

        log.info(
            "seed.catalog.done",
            brand=brand.name,
            series=series.name,
            total=len(products),
            created=created,
            updated=updated,
            errors=errors,
        )
        print(
            f"\n✅ Каталог OptiBox Pro загружен:\n"
            f"   бренд:    {brand.name}\n"
            f"   серия:    {series.name}\n"
            f"   всего:    {len(products)}\n"
            f"   создано:  {created}\n"
            f"   обновлено:{updated}\n"
            f"   ошибок:   {errors}\n",
            flush=True,
        )


def main() -> None:
    import asyncio

    try:
        asyncio.run(seed_catalog())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ошибка seed_catalog: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
