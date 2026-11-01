"""API v2: кросс-справочник клиентских артикулов (§16 п.43, этап 7 роадмапа).

Два роутера:
  * ``router``         — `/me/organization/client-sku-mappings[...]`: активная
    организация из контекста (соло-клиент без орги → 422
    ``ORGANIZATION_REQUIRED``); чтение — все участники, запись — OWNER/BUYER;
  * ``manager_router`` — `/manager/organizations/{organizationId}/client-sku-mappings[...]`:
    организация из пути (MANAGER/ADMIN, без membership-проверок).

``apply-csv`` только в клиентском роутере: он мутирует корзину v2, которая
есть только у клиента. PATCH требует ``If-Match`` по версии маппинга (§16
п.43 п.7); DELETE — без If-Match (паттерн адресной книги). Роутеры тонкие:
доменные ошибки сервиса мапятся в RFC 9457 Problem Details.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    parse_if_match,
    problem_responses,
    request_id_for,
)
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.v2.client_sku import (
    ClientSkuApplyCsvIn,
    ClientSkuApplyOut,
    ClientSkuMappingCreate,
    ClientSkuMappingOut,
    ClientSkuMappingUpdate,
    PageMeta,
)
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.services.client_sku import (
    ClientSkuMappingError,
    ClientSkuService,
)

router = APIRouter(
    prefix="/me/organization/client-sku-mappings", tags=["client-sku-mappings"]
)
manager_router = APIRouter(
    prefix="/manager/organizations", tags=["manager:client-sku-mappings"]
)

_CLIENT_PROBLEMS = problem_responses(
    {
        400: "Invalid If-Match",
        401: "Authentication required",
        403: "Writer role required",
        404: "Mapping or product not found",
        409: "Duplicate client SKU or stale version",
        422: "Validation error, no organization or archived product",
    }
)


def _as_v2_problem(exc: ClientSkuMappingError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _mapping_out(mapping) -> ClientSkuMappingOut:
    """Ручная проекция ORM → DTO (from_attributes в V2Model не включён)."""
    return ClientSkuMappingOut(
        id=mapping.id,
        organization_id=mapping.organization_id,
        client_sku=mapping.client_sku,
        product_id=mapping.product_id,
        note=mapping.note,
        version=mapping.version,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def _patch_changes(payload: ClientSkuMappingUpdate) -> dict[str, object]:
    """Явно переданные поля → changes (паттерн _patch_changes адресов).

    absent сохраняет прежнее значение; ``note: null`` очищает заметку;
    ``productId: null`` — 422 (NOT NULL колонка).
    """
    changes: dict[str, object] = {}
    if "product_id" in payload.model_fields_set:
        if payload.product_id is None:
            raise V2ProblemError(
                code="VALIDATION_ERROR",
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Ошибка валидации",
                detail="Поле productId обязательно и не может быть null",
            )
        changes["product_id"] = payload.product_id
    if "note" in payload.model_fields_set:
        changes["note"] = payload.note
    return changes


@router.get(
    "",
    response_model=SuccessResponse[list[ClientSkuMappingOut]],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def list_mappings(
    request: Request,
    query: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[list[ClientSkuMappingOut]]:
    """Страница справочника организации, свежие связки сверху."""
    try:
        rows, total = await ClientSkuService(db).list_page(
            user, query=query, page=page, page_size=page_size
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[list[ClientSkuMappingOut]](
        data=[_mapping_out(mapping) for mapping in rows],
        meta=PageMeta(
            request_id=request_id_for(request),
            page=page,
            page_size=page_size,
            total=total,
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ClientSkuMappingOut],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def create_mapping(
    request: Request,
    payload: ClientSkuMappingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ClientSkuMappingOut]:
    try:
        mapping = await ClientSkuService(db).create(
            user,
            client_sku=payload.client_sku,
            product_id=payload.product_id,
            note=payload.note,
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return SuccessResponse[ClientSkuMappingOut](
        data=_mapping_out(mapping),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.post(
    "/apply-csv",
    response_model=SuccessResponse[ClientSkuApplyOut],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def apply_csv(
    request: Request,
    payload: ClientSkuApplyCsvIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ClientSkuApplyOut]:
    """Применить CSV-вставку: отчёт + наполнение корзины v2 (§16 п.43)."""
    try:
        report = await ClientSkuService(db).apply_csv(user, csv_text=payload.csv)
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return SuccessResponse[ClientSkuApplyOut](
        data=report,
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.patch(
    "/{mappingId}",
    response_model=SuccessResponse[ClientSkuMappingOut],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def update_mapping(
    request: Request,
    payload: ClientSkuMappingUpdate,
    mapping_id: uuid.UUID = Path(alias="mappingId"),
    if_match: str = Header(..., alias="If-Match"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ClientSkuMappingOut]:
    """Перемапить товар/править заметку. If-Match — по версии маппинга."""
    expected_version = parse_if_match(if_match)
    try:
        mapping = await ClientSkuService(db).update(
            user,
            mapping_id=mapping_id,
            expected_version=expected_version,
            changes=_patch_changes(payload),
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return SuccessResponse[ClientSkuMappingOut](
        data=_mapping_out(mapping),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.delete(
    "/{mappingId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_CLIENT_PROBLEMS,
)
async def delete_mapping(
    request: Request,
    mapping_id: uuid.UUID = Path(alias="mappingId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Удалить связку — без If-Match (паттерн адресной книги)."""
    try:
        await ClientSkuService(db).delete(user, mapping_id=mapping_id)
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Manager-роутер: ведение справочника за клиента (MANAGER/ADMIN) ----------


@manager_router.get(
    "/{organizationId}/client-sku-mappings",
    response_model=SuccessResponse[list[ClientSkuMappingOut]],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def manager_list_mappings(
    request: Request,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    query: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[list[ClientSkuMappingOut]]:
    try:
        rows, total = await ClientSkuService(db).list_page(
            manager,
            query=query,
            page=page,
            page_size=page_size,
            organization_id=organization_id,
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[list[ClientSkuMappingOut]](
        data=[_mapping_out(mapping) for mapping in rows],
        meta=PageMeta(
            request_id=request_id_for(request),
            page=page,
            page_size=page_size,
            total=total,
        ),
    )


@manager_router.post(
    "/{organizationId}/client-sku-mappings",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[ClientSkuMappingOut],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def manager_create_mapping(
    request: Request,
    payload: ClientSkuMappingCreate,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ClientSkuMappingOut]:
    try:
        mapping = await ClientSkuService(db).create(
            manager,
            client_sku=payload.client_sku,
            product_id=payload.product_id,
            note=payload.note,
            organization_id=organization_id,
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return SuccessResponse[ClientSkuMappingOut](
        data=_mapping_out(mapping),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.patch(
    "/{organizationId}/client-sku-mappings/{mappingId}",
    response_model=SuccessResponse[ClientSkuMappingOut],
    response_model_by_alias=True,
    responses=_CLIENT_PROBLEMS,
)
async def manager_update_mapping(
    request: Request,
    payload: ClientSkuMappingUpdate,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    mapping_id: uuid.UUID = Path(alias="mappingId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[ClientSkuMappingOut]:
    expected_version = parse_if_match(if_match)
    try:
        mapping = await ClientSkuService(db).update(
            manager,
            mapping_id=mapping_id,
            expected_version=expected_version,
            changes=_patch_changes(payload),
            organization_id=organization_id,
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return SuccessResponse[ClientSkuMappingOut](
        data=_mapping_out(mapping),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@manager_router.delete(
    "/{organizationId}/client-sku-mappings/{mappingId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_CLIENT_PROBLEMS,
)
async def manager_delete_mapping(
    request: Request,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    mapping_id: uuid.UUID = Path(alias="mappingId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await ClientSkuService(db).delete(
            manager, mapping_id=mapping_id, organization_id=organization_id
        )
    except ClientSkuMappingError as exc:
        raise _as_v2_problem(exc) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["manager_router", "router"]
