"""Сервис менеджер-панели: товары (ручная цена/статус), бренды, фото серий.

См. §6, §16 п.20-2/3. Коммит выполняет сервис; аудит — repositories/audit.py;
мутации каталога после commit инвалидируют теги catalog/filters (fail-open).
Ошибки: NotFoundError → 404, ConflictError → 409, InvalidImageError → 415,
прочий ValueError → 422.
"""
import io
import uuid
from decimal import Decimal

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.catalog import Brand
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import manager_catalog as repo
from app.repositories.catalog import PHOTO_KEY_PREFIX, _slugify, get_brand, get_series
from app.schemas.manager_catalog import (
    BrandCreateIn,
    BrandOut,
    BrandRenameIn,
    ManagerBrandRef,
    ManagerProductPatchIn,
    ManagerProductRead,
    ManagerSeriesRef,
    SeriesPhotoOut,
)
from app.services import storage
from app.services.cache import CATALOG_TAG, FILTERS_TAG, invalidate_tags

# Геометрия фото серий — зеркалит tasks/photo_zip.py (webp large/thumb, q=82).
LARGE_SIZE = (1200, 1200)   # fit без кропа
THUMB_SIZE = (400, 400)
WEBP_QUALITY = 82


class NotFoundError(ValueError):
    """Товар/бренд/серия не найдены → 404."""


class ConflictError(ValueError):
    """Конфликт состояния (бренд с сериями/товарами) → 409."""


class InvalidImageError(ValueError):
    """Файл не открывается Pillow → 415."""


def _json_price(value) -> str | None:
    """Decimal → str для JSONB аудита (None — сброшенная ручная цена)."""
    return str(value) if value is not None else None


def _process_image(raw: bytes) -> tuple[bytes, bytes]:
    """Pillow: large (fit 1200×1200) и thumb (fit 400×400), webp quality 82.

    Зеркалит tasks/photo_zip._process_image: обе производные строятся из
    исходника (``convert("RGB")`` возвращает копию и заодно приводит RGBA/P).
    ``thumbnail`` только уменьшает (без кропа и без увеличения).
    """
    with Image.open(io.BytesIO(raw)) as img:
        large_img = img.convert("RGB")
        large_img.thumbnail(LARGE_SIZE)
        thumb_img = img.convert("RGB")
        thumb_img.thumbnail(THUMB_SIZE)
        return _to_webp(large_img), _to_webp(thumb_img)


def _to_webp(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()


class ManagerCatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------ товары
    async def list_products(
        self,
        *,
        q: str | None,
        brand_id: uuid.UUID | None,
        stock,
        page: int,
        per_page: int,
    ) -> tuple[list[ManagerProductRead], int]:
        rows, total = await repo.fetch_manager_products(
            self.db,
            q=q,
            brand_id=brand_id,
            stock=stock,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return [self._product_read(row) for row in rows], total

    async def update_product(
        self, manager: User, product_id: uuid.UUID, payload: ManagerProductPatchIn
    ) -> ManagerProductRead:
        """Изменить override_price (null — сброс) и/или stock_status + аудит."""
        product = await repo.get_active_product(self.db, product_id)
        if product is None:
            raise NotFoundError("Товар не найден")

        data = payload.model_dump(exclude_unset=True)
        before: dict = {}
        after: dict = {}
        if "override_price" in data:  # поле передано явно: null = сброс
            new_price = data["override_price"]
            if product.override_price != new_price:
                before["override_price"] = _json_price(product.override_price)
                after["override_price"] = _json_price(new_price)
                product.override_price = new_price
        if data.get("stock_status") is not None and product.stock_status != data["stock_status"]:
            before["stock_status"] = product.stock_status.value
            after["stock_status"] = data["stock_status"].value
            product.stock_status = data["stock_status"]

        if after:
            await audit_repo.create_audit(
                self.db,
                actor_id=manager.id,
                action="product.update",
                target_type="product",
                target_id=product.id,
                before=before,
                after=after,
            )
            await self.db.commit()
            await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
        row = await repo.get_manager_product(self.db, product_id)
        if row is None:  # практически невозможно: товар только что коммитился
            raise NotFoundError("Товар не найден")
        return self._product_read(row)

    @staticmethod
    def _product_read(row) -> ManagerProductRead:
        return ManagerProductRead(
            id=row.id,
            sku=row.sku,
            name=row.name,
            base_price=Decimal(str(row.base_price)),
            override_price=(
                Decimal(str(row.override_price)) if row.override_price is not None else None
            ),
            stock_status=row.stock_status,
            brand=ManagerBrandRef(id=row.brand_id, name=row.brand_name)
            if row.brand_id is not None
            else None,
            series=ManagerSeriesRef(id=row.series_id, name=row.series_name)
            if row.series_id is not None
            else None,
        )

    # ------------------------------------------------------------ бренды
    async def list_brands(self) -> list[BrandOut]:
        rows = await repo.fetch_brands_with_counts(self.db)
        return [self._brand_out(row) for row in rows]

    async def create_brand(self, manager: User, payload: BrandCreateIn) -> BrandOut:
        slug = await repo.generate_unique_slug(self.db, payload.name)
        brand = Brand(name=payload.name, slug=slug)
        self.db.add(brand)
        await self.db.flush()
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="brand.create",
            target_type="brand",
            target_id=brand.id,
            after={"name": brand.name, "slug": slug},
        )
        await self.db.commit()
        await self.db.refresh(brand)
        await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
        return BrandOut(id=brand.id, name=brand.name, slug=brand.slug,
                        series_count=0, products_count=0)

    async def rename_brand(
        self, manager: User, brand_id: uuid.UUID, payload: BrandRenameIn
    ) -> BrandOut:
        """Переименование: slug НЕ меняется — стабильные ключи фото серий."""
        brand = await get_brand(self.db, brand_id)
        if brand is None:
            raise NotFoundError("Бренд не найден")
        if brand.name != payload.name:
            before = {"name": brand.name}
            brand.name = payload.name
            await audit_repo.create_audit(
                self.db,
                actor_id=manager.id,
                action="brand.update",
                target_type="brand",
                target_id=brand.id,
                before=before,
                after={"name": brand.name},
            )
            await self.db.commit()
            await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
        row = await repo.get_brand_with_counts(self.db, brand_id)
        if row is None:
            raise NotFoundError("Бренд не найден")
        return self._brand_out(row)

    async def delete_brand(self, manager: User, brand_id: uuid.UUID) -> None:
        """Удалить бренд (только строку бренда). Есть серии/товары → 409."""
        brand = await get_brand(self.db, brand_id)
        if brand is None:
            raise NotFoundError("Бренд не найден")
        has_series, has_products = await repo.brand_has_children(self.db, brand_id)
        if has_series or has_products:
            raise ConflictError("Нельзя удалить бренд, у которого есть серии или товары")
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="brand.delete",
            target_type="brand",
            target_id=brand.id,
            before={"name": brand.name, "slug": brand.slug},
        )
        await self.db.delete(brand)
        await self.db.commit()
        await invalidate_tags(CATALOG_TAG, FILTERS_TAG)

    @staticmethod
    def _brand_out(row) -> BrandOut:
        return BrandOut(
            id=row.id,
            name=row.name,
            slug=row.slug,
            series_count=int(row.series_count),
            products_count=int(row.products_count),
        )

    # -------------------------------------------------------- фото серии
    async def upload_series_photo(
        self, manager: User, series_id: uuid.UUID, raw: bytes
    ) -> SeriesPhotoOut:
        """Обработать и залить фото серии (webp large+thumb), обновить photo_key.

        Ключи — как у photo-ZIP (tasks/photo_zip.py): ``photos-series/{slug}``,
        где slug = нормализованное имя серии (``_slugify``), чтобы ZIP-загрузка
        и ручная заливка писали в одни и те же объекты.
        """
        series = await get_series(self.db, series_id)
        if series is None:
            raise NotFoundError("Серия не найдена")

        try:
            large, thumb = await run_in_threadpool(_process_image, raw)
        except Exception as exc:
            raise InvalidImageError("Файл не является корректным изображением") from exc

        slug = _slugify(series.name)
        key_large = f"{PHOTO_KEY_PREFIX}{slug}.webp"
        key_thumb = f"{PHOTO_KEY_PREFIX}{slug}_thumb.webp"
        await run_in_threadpool(
            storage.upload_fileobj,
            settings.s3_bucket_photos,
            key_large,
            io.BytesIO(large),
            content_type="image/webp",
        )
        await run_in_threadpool(
            storage.upload_fileobj,
            settings.s3_bucket_photos,
            key_thumb,
            io.BytesIO(thumb),
            content_type="image/webp",
        )

        series.photo_key = key_large
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="series.photo.update",
            target_type="series",
            target_id=series.id,
            after={"photo_key": key_large},
        )
        await self.db.commit()
        await invalidate_tags(CATALOG_TAG, FILTERS_TAG)
        return SeriesPhotoOut(
            photo_key=key_large,
            photo_url=f"/api/v1/files/photo?key={key_large}",
        )
