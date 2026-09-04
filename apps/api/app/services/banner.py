"""Сервис баннеров главной страницы (публичная выдача + админский CRUD)."""
import io
import uuid

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.enums import BannerPosition
from app.repositories import banner as banner_repo
from app.schemas.banner import BannerCreate, BannerRead, BannerUpdate
from app.services import storage


class NotFoundError(ValueError):
    """Баннер не найден."""


class InvalidImageError(ValueError):
    """Файл не является корректным изображением."""


class BannerService:
    """Баннеры: публичный список и CRUD для менеджера."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_public(self, position: BannerPosition | None) -> list[BannerRead]:
        rows = await banner_repo.fetch_active(self.db, position=position)
        return [BannerRead.model_validate(row) for row in rows]

    async def list_admin(self) -> list[BannerRead]:
        rows = await banner_repo.fetch_all(self.db)
        return [BannerRead.model_validate(row) for row in rows]

    async def create(self, payload: BannerCreate) -> BannerRead:
        banner = await banner_repo.create(self.db, **payload.model_dump())
        return BannerRead.model_validate(banner)

    async def update(self, banner_id: uuid.UUID, payload: BannerUpdate) -> BannerRead:
        banner = await banner_repo.get_by_id(self.db, banner_id)
        if banner is None:
            raise NotFoundError("Баннер не найден")
        fields = payload.model_dump(exclude_unset=True)
        banner = await banner_repo.update(self.db, banner, **fields)
        return BannerRead.model_validate(banner)

    async def delete(self, banner_id: uuid.UUID) -> None:
        banner = await banner_repo.get_by_id(self.db, banner_id)
        if banner is None:
            raise NotFoundError("Баннер не найден")
        await banner_repo.delete(self.db, banner)

    async def upload_image(self, raw: bytes, ext: str) -> str:
        """Залить картинку баннера в photos-бакет, вернуть S3-ключ.

        Ключ: ``banners/{uuid}.{ext}``; отдача — через GET /api/v1/files/photo?key=.
        """
        try:
            with Image.open(io.BytesIO(raw)) as img:
                img.verify()
        except Exception as exc:
            raise InvalidImageError("Файл не является корректным изображением") from exc

        key = f"banners/{uuid.uuid4()}{ext}"
        content_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }[ext]
        await run_in_threadpool(
            storage.put_bytes,
            settings.s3_bucket_photos,
            key,
            raw,
            content_type=content_type,
        )
        return key
