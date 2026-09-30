"""Manager-only API v2 organization control-plane routes."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    parse_if_match,
    problem_responses,
    request_id_for,
)
from app.api.v2.pagination import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    filter_signature,
)
from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User
from app.schemas.v2.common import (
    CursorMeta,
    CursorResponse,
    ResponseMeta,
    SuccessResponse,
)
from app.schemas.v2.invoices import OrganizationBillingPatch
from app.schemas.v2.organizations import (
    OrganizationDetail,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberPatch,
    OrganizationSummary,
)
from app.services.invoice import InvoiceError, InvoiceService, StaleResourceVersionError
from app.services.organizations import (
    MembershipTargetNotFoundError,
    OrganizationManagementError,
    OrganizationManagementService,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])

# Реквизиты для счёта на оплату живут на отдельном manager-префиксе (§6
# «Счета на оплату», §16 п.40 п.4): правка печатных реквизитов — привилегия
# менеджера и требует If-Match, а чтение остаётся на общем /organizations/{id}.
manager_router = APIRouter(
    prefix="/manager/organizations", tags=["manager:organizations"]
)

_ORGANIZATION_SORT = Literal["legalName", "-legalName", "createdAt", "-createdAt"]
_MEMBER_SORT = Literal[
    "fullName", "-fullName", "email", "-email", "createdAt", "-createdAt"
]


def _cursor_problem() -> V2ProblemError:
    return V2ProblemError(
        code="VALIDATION_ERROR",
        status=422,
        title="Ошибка валидации",
        detail="Курсор пагинации недействителен",
    )


def _decode_organization_cursor(
    cursor: str | None, *, resource: str, sort: str, q: str | None
) -> dict[str, str] | None:
    if cursor is None:
        return None
    try:
        return decode_cursor(
            cursor,
            resource=resource,
            sort=sort,
            filter_sig=filter_signature(q),
        )
    except InvalidCursorError as exc:
        raise _cursor_problem() from exc


def _organization_cursor_value(organization: Organization, sort: str) -> str:
    return (
        organization.created_at.isoformat()
        if sort in {"createdAt", "-createdAt"}
        else organization.legal_name
    )


def _member_cursor_value(record, sort: str) -> str:
    if sort in {"createdAt", "-createdAt"}:
        return record.membership.created_at.isoformat()
    if sort in {"email", "-email"}:
        return record.user.email
    return record.user.full_name


def _as_v2_problem(exc: OrganizationManagementError) -> V2ProblemError:
    return V2ProblemError(
        code=exc.code,
        status=exc.status_code,
        title=exc.title,
        detail=exc.detail,
    )


def _organization_summary(organization: Organization) -> OrganizationSummary:
    return OrganizationSummary(
        id=organization.id,
        legal_name=organization.legal_name,
        display_name=organization.display_name,
        tax_id=organization.tax_id,
        country_code=organization.country_code,
        default_currency=organization.default_currency,
        is_active=organization.is_active,
        version=organization.version,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def _organization_detail(organization: Organization) -> OrganizationDetail:
    return OrganizationDetail(
        **_organization_summary(organization).model_dump(),
        legal_address=organization.legal_address,
        legal_email=organization.legal_email,
        legal_phone=organization.legal_phone,
        bank_name=organization.bank_name,
        bank_code=organization.bank_code,
        bank_account=organization.bank_account,
    )


def _member(membership: OrganizationMembership, user: User) -> OrganizationMember:
    return OrganizationMember(
        organization_id=membership.organization_id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        role=membership.role,
        is_active=membership.is_active,
        is_primary=membership.is_primary,
        version=membership.version,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.get(
    "",
    response_model=CursorResponse[OrganizationSummary],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_organizations(
    request: Request,
    q: str | None = Query(default=None, max_length=255),
    sort: _ORGANIZATION_SORT = Query(default="legalName"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[OrganizationSummary]:
    normalized_q = q.strip() if q else None
    after = _decode_organization_cursor(
        cursor, resource="organizations", sort=sort, q=normalized_q
    )
    try:
        rows = await OrganizationManagementService(db).list_organizations_page(
            _manager,
            query=normalized_q,
            sort=sort,
            limit=limit + 1,
            after=after,
        )
    except OrganizationManagementError as exc:
        raise _as_v2_problem(exc) from exc
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(
            resource="organizations",
            sort=sort,
            filter_sig=filter_signature(normalized_q),
            value=_organization_cursor_value(rows[-1], sort),
            item_id=rows[-1].id,
        )
        if has_more and rows
        else None
    )
    return CursorResponse[OrganizationSummary](
        data=[_organization_summary(organization) for organization in rows],
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=sort,
        ),
    )


@router.get(
    "/{organizationId}",
    response_model=SuccessResponse[OrganizationDetail],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_organization(
    request: Request,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationDetail]:
    try:
        organization = await OrganizationManagementService(db).get_organization(
            manager, organization_id=organization_id
        )
    except OrganizationManagementError as exc:
        raise _as_v2_problem(exc) from exc
    return SuccessResponse[OrganizationDetail](
        data=_organization_detail(organization),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.get(
    "/{organizationId}/members",
    response_model=CursorResponse[OrganizationMember],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_members(
    request: Request,
    q: str | None = Query(default=None, max_length=255),
    sort: _MEMBER_SORT = Query(default="fullName"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    organization_id: uuid.UUID = Path(alias="organizationId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> CursorResponse[OrganizationMember]:
    normalized_q = q.strip() if q else None
    resource = f"organization-members:{organization_id}"
    after = _decode_organization_cursor(
        cursor, resource=resource, sort=sort, q=normalized_q
    )
    try:
        records = await OrganizationManagementService(db).list_members_page(
            manager,
            organization_id=organization_id,
            query=normalized_q,
            sort=sort,
            limit=limit + 1,
            after=after,
        )
    except OrganizationManagementError as exc:
        raise _as_v2_problem(exc) from exc
    has_more = len(records) > limit
    records = records[:limit]
    next_cursor = (
        encode_cursor(
            resource=resource,
            sort=sort,
            filter_sig=filter_signature(normalized_q),
            value=_member_cursor_value(records[-1], sort),
            item_id=records[-1].user.id,
        )
        if has_more and records
        else None
    )
    return CursorResponse[OrganizationMember](
        data=[_member(record.membership, record.user) for record in records],
        meta=CursorMeta(
            request_id=request_id_for(request),
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit,
            sort=sort,
        ),
    )


@router.post(
    "/{organizationId}/members",
    status_code=201,
    response_model=SuccessResponse[OrganizationMember],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid membership target",
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization or target user not found",
            409: "Membership already exists",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def add_member(
    request: Request,
    payload: OrganizationMemberCreate,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationMember]:
    try:
        membership = await OrganizationManagementService(db).add_member(
            manager,
            organization_id=organization_id,
            user_id=payload.user_id,
            role=payload.role,
            is_active=payload.is_active,
            is_primary=payload.is_primary,
        )
        target = await db.get(User, payload.user_id)
        if target is None:
            raise MembershipTargetNotFoundError("Пользователь для участника не найден")
        response = SuccessResponse[OrganizationMember](
            data=_member(membership, target),
            meta=ResponseMeta(request_id=request_id_for(request)),
        )
        await db.commit()
        return response
    except OrganizationManagementError as exc:
        raise _as_v2_problem(exc) from exc


@router.patch(
    "/{organizationId}/members/{userId}",
    response_model=SuccessResponse[OrganizationMember],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid membership update or If-Match",
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization or membership not found",
            409: "Stale version or last owner protection",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def update_member(
    request: Request,
    payload: OrganizationMemberPatch,
    organization_id: uuid.UUID = Path(alias="organizationId"),
    user_id: uuid.UUID = Path(alias="userId"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationMember]:
    try:
        expected_version = parse_if_match(if_match)
        membership = await OrganizationManagementService(db).update_member(
            manager,
            organization_id=organization_id,
            user_id=user_id,
            expected_version=expected_version,
            role=payload.role,
            is_active=payload.is_active,
            is_primary=payload.is_primary,
            body_version=payload.version,
        )
        target = await db.get(User, user_id)
        if target is None:
            raise MembershipTargetNotFoundError("Пользователь для участника не найден")
        response = SuccessResponse[OrganizationMember](
            data=_member(membership, target),
            meta=ResponseMeta(request_id=request_id_for(request)),
        )
        await db.commit()
        return response
    except OrganizationManagementError as exc:
        raise _as_v2_problem(exc) from exc


@manager_router.patch(
    "/{id}",
    response_model=SuccessResponse[OrganizationDetail],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid If-Match",
            401: "Authentication required",
            403: "Manager role required",
            404: "Organization not found",
            409: "Stale resource version",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def update_organization_billing(
    request: Request,
    payload: OrganizationBillingPatch,
    organization_id: uuid.UUID = Path(alias="id"),
    if_match: str = Header(..., alias="If-Match"),
    manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[OrganizationDetail]:
    """Реквизиты организации для счёта на оплату (§6, §16 п.40 п.4).

    ``If-Match`` сверяет ``organizations.version`` (не версию счёта и не
    заказа): реквизиты общие для всех счетов организации, поэтому конкурируют
    между собой правки менеджеров, а не операции со счётом. Аудит —
    ``organization.update``.
    """
    try:
        expected_version = parse_if_match(if_match)
        if payload.version is not None and payload.version != expected_version:
            raise StaleResourceVersionError(
                "Версия организации в теле не совпадает с If-Match"
            )
        organization = await InvoiceService(db).update_organization_billing(
            manager,
            organization_id,
            expected_version=expected_version,
            patch=payload,
        )
        result = SuccessResponse[OrganizationDetail](
            data=_organization_detail(organization),
            meta=ResponseMeta(request_id=request_id_for(request)),
        )
        await db.commit()
        return result
    except InvoiceError as exc:
        raise _as_v2_problem(exc) from exc


__all__ = ["manager_router", "router"]
