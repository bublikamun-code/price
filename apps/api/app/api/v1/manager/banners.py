"""Роутер баннеров менеджера (/api/v1/manager/banners). См. §6.

CRUD баннеров главной страницы + загрузка картинки (multipart, jpeg/png/webp
до 10 МБ, ключ ``banners/{uuid}.{ext}`` в photos-бакете). Роль MANAGER (§11).
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.banner import BannerCreate, BannerRead, BannerUpdate
from app.services import storage
from app.services.banner import BannerService, InvalidImageError, NotFoundError

router = APIRouter(prefix="/banners", tags=["manager:banners"])

# Лимиты картинки баннера: формат и размер (jpeg/png/webp, до 10 МБ).
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_BYTES = 10 * 1024 * 1024
_READ_CHUNK = 1024 * 1024


def _to_http(exc: ValueError) -> HTTPException:
    """NotFoundError → 404, InvalidImageError → 400, прочие ValueError → 422."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, InvalidImageError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


async def _read_capped(file: UploadFile) -> bytes:
    """Прочитать файл в память с лимитом 10 МБ."""
    buf = bytearray()
    while chunk := await file.read(_READ_CHUNK):
        buf.extend(chunk)
        if len(buf) > _MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл превышает лимит 10 МБ",
            )
    return bytes(buf)


@router.get("", response_model=list[BannerRead])
async def list_banners(
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> list[BannerRead]:
    """Все баннеры (включая скрытые), сортировка position, sort."""
    return await BannerService(db).list_admin()


@router.post("", response_model=BannerRead, status_code=status.HTTP_201_CREATED)
async def create_banner(
    payload: BannerCreate,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> BannerRead:
    banner = await BannerService(db).create(payload)
    await db.commit()
    return banner


@router.patch("/{banner_id}", response_model=BannerRead)
async def update_banner(
    banner_id: uuid.UUID,
    payload: BannerUpdate,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> BannerRead:
    try:
        banner = await BannerService(db).update(banner_id, payload)
    except ValueError as exc:
        raise _to_http(exc) from exc
    await db.commit()
    return banner


@router.delete("/{banner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_banner(
    banner_id: uuid.UUID,
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await BannerService(db).delete(banner_id)
    except ValueError as exc:
        raise _to_http(exc) from exc
    await db.commit()


@router.post("/image", status_code=status.HTTP_201_CREATED)
async def upload_banner_image(
    file: UploadFile = File(..., description="Картинка баннера (jpg/jpeg/png/webp, до 10 МБ)"),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Загрузить картинку баннера в photos-бакет (ключ banners/{uuid}.{ext})."""
    name = (file.filename or "").lower()
    ext = next((e for e in _ALLOWED_IMAGE_EXTENSIONS if name.endswith(e)), None)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Допустимы только файлы: {', '.join(sorted(_ALLOWED_IMAGE_EXTENSIONS))}",
        )
    raw = await _read_capped(file)
    try:
        key = await BannerService(db).upload_image(raw, ext)
    except InvalidImageError as exc:
        raise _to_http(exc) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return {"key": key}
