"""Публичная SEO-витрина (/api/v1/public). См. §6, SITEMAP §5, §16 п.29.

Без аутентификации и без цен/остатков/ПДн: бренды → серии → номенклатура.

  * GET /brands                 — список брендов ({data: [...]});
  * GET /brands/{slug}          — бренд + серии ({data: {...}});
  * GET /series/{slug}/products — номенклатура серии ({data, meta};
    пагинация page/per_page, кап per_page=200 как в каталоге);
  * GET /photo?key=             — фото серии из бакета photos-series.

slug серии — её UUID (модель Series без slug-колонки); фронту он возвращается
деталкой бренда и ходит по кругу как непрозрачный токен (см. services/public_catalog.py).

/photo — произвольное чтение объектов S3 недопустимо, ключ строго в whitelist:
только префикс ``photos-series/`` (фото серий и их миниатюры; объекты
``photos-product/…`` и всё прочее запрещены), без схемы и ``..`` (path traversal),
расширение из {jpg, jpeg, png, webp}. Отдаём стримом, а не редиректом на
presigned URL: внешний S3-эндпоинт может иметь невалидный TLS — та же проблема
и то же решение, что в api/v1/files.py (GET /files/photo).
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import PUBLIC_RATE_LIMIT, limiter
from app.db.session import get_db
from app.repositories.catalog import PHOTO_KEY_PREFIX
from app.repositories.notifications import create_notification
from app.schemas import MetaPage
from app.schemas.public import (
    PublicBrandDetailEnvelope,
    PublicBrandListEnvelope,
    PublicLeadAccepted,
    PublicLeadIn,
    PublicSeriesProductsEnvelope,
)
from app.services import storage
from app.services.notification_events import notification_payload, publish_notification
from app.services.public_catalog import NotFoundError, PublicCatalogService

router = APIRouter(prefix="/public", tags=["public"])

# Ключ — путь внутри бакета: без схемы (http://, s3://…) и без «..».
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)

# Whitelist расширений публичных фото (пайплайн пишет webp; jpg/png — на всякий
# случай для legacy-ключей). Всё остальное (pdf, svg, без расширения) — 400.
_ALLOWED_PHOTO_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png")
_PHOTO_MEDIA_TYPES = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


# Ключи галерей товаров (наш пайплайн): photos-product/<uuid>/<8hex>[/_thumb].webp
_PRODUCT_KEY_RE = re.compile(
    r"^photos-product/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/[0-9a-f]{8}(_thumb)?\.webp$"
)


def _validate_public_photo_key(key: str) -> str:
    """Whitelist-валидация ключа публичного фото (анти arbitrary-file-read).

    Разрешены: фото серий ``photos-series/…`` и галерейные ключи товаров
    ``photos-product/<uuid>/<8hex>.webp`` (витрина брендов на лендинге).
    """
    key = key.strip().lstrip("/")
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой ключ")
    key_ok = key.startswith(PHOTO_KEY_PREFIX) or _PRODUCT_KEY_RE.match(key)
    if ".." in key or _SCHEME_RE.match(key) or not key_ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый ключ файла"
        )
    if not key.endswith(_ALLOWED_PHOTO_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый тип файла"
        )
    return key


@router.get("/brands", response_model=PublicBrandListEnvelope)
@limiter.limit(PUBLIC_RATE_LIMIT)
async def list_brands(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PublicBrandListEnvelope:
    """Список брендов для витрины (по имени)."""
    brands = await PublicCatalogService(db).list_brands()
    return PublicBrandListEnvelope(data=brands)


@router.get("/brands/{slug}", response_model=PublicBrandDetailEnvelope)
@limiter.limit(PUBLIC_RATE_LIMIT)
async def get_brand(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> PublicBrandDetailEnvelope:
    """Бренд + его серии (серии без товаров тоже показываем)."""
    try:
        detail = await PublicCatalogService(db).get_brand(slug)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return PublicBrandDetailEnvelope(data=detail)


@router.get("/series/{slug}/products", response_model=PublicSeriesProductsEnvelope)
async def list_series_products(
    slug: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> PublicSeriesProductsEnvelope:
    """Номенклатура серии (sku + наименование, без цен/остатков)."""
    service = PublicCatalogService(db)
    try:
        items, total = await service.series_products(slug, page=page, per_page=per_page)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return PublicSeriesProductsEnvelope(
        data=items, meta=MetaPage(page=page, per_page=per_page, total=total)
    )


@router.get("/photo")
async def get_photo(
    key: str = Query(description="S3-ключ фото серии (photos-series/…)"),
) -> Response:
    """Фото серии из бакета ``photos-series`` — без аутентификации (витрина).

    Ключ только из whitelist (см. docstring модуля). Объект не найден /
    хранилище недоступно → 404/502 как в files.py.
    """
    valid_key = _validate_public_photo_key(key)
    try:
        data = await run_in_threadpool(
            storage.get_bytes, settings.s3_bucket_photos, valid_key
        )
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Фото не найдено"
        ) from exc
    ext = next((e for e in _ALLOWED_PHOTO_EXTENSIONS if valid_key.endswith(e)), "")
    media_type = _PHOTO_MEDIA_TYPES.get(ext, "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        # Публичные неизменяемые ассеты (ключ содержит uuid/hash) — кэшируем
        # агрессивно: без этого каждое касание фильтров перезапрашивает все фото
        # и карточки «моргают» (аудит UX 19.09).
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# Заявка на доступ с лендинга: лид уходит всем менеджерам (in-app + telegram).
# Лимит строже витрины: форма — цель спама.
LEAD_RATE_LIMIT = "5/10minutes"


@router.post("/lead", response_model=PublicLeadAccepted, status_code=status.HTTP_201_CREATED)
@limiter.limit(LEAD_RATE_LIMIT)
async def create_lead(
    request: Request,
    payload: PublicLeadIn,
    db: AsyncSession = Depends(get_db),
) -> PublicLeadAccepted:
    """Публичная лид-форма лендинга (§6): без авторизации, уведомление менеджерам.

    CSRF не применяется (как у витрины: анонимный запрос без сессии).
    """
    # Honeypot: боты заполняют скрытое поле «сайт». Отвечаем успехом, ничего не делая.
    if payload.website.strip():
        return PublicLeadAccepted(ok=True)

    contact = f"{payload.contact_name}, тел. {payload.phone}"
    if payload.email:
        contact += f", {payload.email}"
    body = f"Компания: {payload.company}\n{contact}"
    if payload.comment:
        body += f"\nКомментарий: {payload.comment}"

    notif = await create_notification(
        db,
        type="LEAD_CREATED",
        title="Новая заявка с лендинга",
        body=body,
        user_id=None,  # None → всем менеджерам (§20)
        channel=["inapp", "telegram"],
        payload={
            "company": payload.company,
            "contact_name": payload.contact_name,
            "phone": payload.phone,
            "email": payload.email,
            "comment": payload.comment,
        },
    )
    # SSE-событие менеджерам: мгновенная доставка, fail-open (§16 п.26).
    publish_notification(notification_payload(notif), user_id=None)
    await db.commit()
    return PublicLeadAccepted(ok=True)


# Публичный PDF-каталог (лид-магнит лендинга): рендер weasyprint тяжёлый,
# состав меняется только импортом — кэшируем байты на час в процессе.
_CATALOG_PDF_TTL = 60 * 60
_catalog_pdf_cache: dict[str, bytes] = {}


@router.get("/catalog.pdf", response_class=Response)
@limiter.limit("10/minute")
async def download_catalog_pdf(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF-каталог для гостей: бренды → серии → номенклатура, без цен (§6)."""
    import datetime as dt

    cache_key = "public_catalog_pdf"
    cached = _catalog_pdf_cache.get(cache_key)
    if cached is None:
        service = PublicCatalogService(db)
        brands_out = []
        for brand in await service.list_brands():
            detail = await service.get_brand(brand.slug)
            series_blocks = []
            for series in detail.series:
                products, _total = await service.series_products(
                    series.slug, page=1, per_page=200
                )
                series_blocks.append(
                    {
                        "name": series.name,
                        "products": [
                            {"name": p.name, "sku": p.sku} for p in products
                        ],
                    }
                )
            brands_out.append({"name": brand.name, "series": series_blocks})

        from app.core.templates import render_pdf

        html = render_pdf(
            "public_catalog.j2",
            brands=brands_out,
            date=dt.datetime.now(dt.UTC).strftime("%d.%m.%Y"),
        )
        from weasyprint import HTML  # лениво, как в export_catalog (§16 п.25)

        # WeasyPrint выполняет тяжёлое CPU-рендеринг, поэтому его нельзя
        # запускать прямо в event loop async-хендлера.
        cached = await run_in_threadpool(HTML(string=html).write_pdf)
        _catalog_pdf_cache[cache_key] = cached

    return Response(
        content=cached,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                'attachment; filename="katalog-svet-v-dome.pdf"'
            ),
            "Cache-Control": "public, max-age=300",
        },
    )
