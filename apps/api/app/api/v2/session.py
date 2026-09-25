"""API v2 current-session endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import (
    V2ProblemError,
    problem_responses,
    request_id_for,
)
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.schemas.v2.organizations import OrganizationSelectionRequest
from app.schemas.v2.session import SessionContext, session_context
from app.services.organizations import (
    OrganizationContextService,
    OrganizationManagementError,
    OrganizationManagementService,
)

router = APIRouter(tags=["session"])


@router.get(
    "/session",
    response_model=SuccessResponse[SessionContext],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def get_session(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SessionContext]:
    context = await OrganizationContextService(db).resolve(user)
    return SuccessResponse[SessionContext](
        data=session_context(user, context),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.put(
    "/session/organization",
    response_model=SuccessResponse[SessionContext],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            400: "Invalid organization selection",
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def select_organization(
    request: Request,
    payload: OrganizationSelectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SessionContext]:
    try:
        context = await OrganizationManagementService(db).select_organization(
            user, organization_id=payload.organization_id
        )
        await db.commit()
    except OrganizationManagementError as exc:
        raise V2ProblemError(
            code=exc.code,
            status=exc.status_code,
            title=exc.title,
            detail=exc.detail,
        ) from exc
    return SuccessResponse[SessionContext](
        data=session_context(user, context),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


__all__ = ["router"]
