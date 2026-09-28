"""API v2 native sessions: login grant, refresh, 2FA challenge, session journal.

Нативный клиент (SwiftUI / Compose поверх общего KMP-ядра) не умеет в
httpOnly-cookie, поэтому grant возвращает оба токена в теле ответа, а refresh
приходит в теле запроса. Доменная логика не дублируется: AuthService о cookie
ничего не знает, здесь только перевод ошибок в Problem Details и сборка DTO
(docs/NATIVE_API_CONTRACT.md §4, ARCHITECTURE_PLAN.md §16 п.36).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.errors import V2ProblemError, problem_responses, request_id_for
from app.core.config import settings
from app.core.deps import get_current_session_id, get_current_user
from app.core.limiter import limiter
from app.core.security import create_2fa_ticket
from app.db.session import get_db
from app.models.user import User
from app.schemas.v2.auth import (
    SessionGrant,
    SessionRefreshRequest,
    SessionRequest,
    SessionSummary,
    TwoFaChallenge,
    TwoFaChallengeRequest,
    session_grant,
    session_summary,
)
from app.schemas.v2.common import ResponseMeta, SuccessResponse
from app.schemas.v2.session import current_user
from app.services.auth import AuthError, AuthService
from app.services.auth_v2 import grant_tokens, to_problem

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _session_metadata(body) -> dict[str, str | None]:
    """Native-метаданные сессии (§16 п.36) → kwargs AuthService._issue_session.

    Только для clientType=NATIVE: у браузера нет «имени устройства», и web-вход
    не должен выдумывать его — иначе журнал сессий перестаёт отличать реальные
    устройства от вкладок (см. модель Session).
    """
    if body.client_type != "NATIVE":
        return {"client_type": body.client_type}
    return {
        "client_type": body.client_type,
        "device_name": body.device_name,
        "os_name": body.os_name,
        "app_version": body.app_version,
    }


def _grant(request: Request, user: User, tokens, session) -> SuccessResponse[SessionGrant]:
    access, refresh, expires_in = grant_tokens(tokens)
    return SuccessResponse[SessionGrant](
        data=session_grant(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
            force_password_change=bool(user.must_change_password),
            session=session,
            user=current_user(user),
        ),
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


def _session_of(user: User, session) -> User:
    """Страховка инварианта grant: сессия выдаётся только активному пользователю."""
    if user is None or not user.is_active:
        raise V2ProblemError(
            code="AUTHENTICATION_REQUIRED",
            status=401,
            title="Требуется авторизация",
            detail="Пользователь неактивен",
        )
    return user


@router.post(
    "/sessions",
    response_model=SuccessResponse[SessionGrant | TwoFaChallenge],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Invalid credentials",
            422: "Validation error",
            429: "Too many attempts",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_login)
async def create_session(
    request: Request,
    body: SessionRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SessionGrant | TwoFaChallenge]:
    """Вход по email+паролю. Возвращает токены в теле, а не в cookie.

    При включённой 2FA токенов нет: ответ — challenge с короткоживущим ticket,
    сессия создаётся только после verify (§16 п.22).
    """
    svc = AuthService(db)
    try:
        user, tokens, session = await svc.login_session(
            email=body.email,
            password=body.password,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
            **_session_metadata(body),
        )
    except AuthError as exc:
        raise to_problem(exc) from exc

    if tokens is None:
        return SuccessResponse[SessionGrant | TwoFaChallenge](
            data=TwoFaChallenge(
                two_fa_required=True,
                ticket=create_2fa_ticket(str(user.id)),
                force_password_change=bool(user.must_change_password),
            ),
            meta=ResponseMeta(request_id=request_id_for(request)),
        )
    return _grant(request, _session_of(user, session), tokens, session)


@router.post(
    "/sessions/refresh",
    response_model=SuccessResponse[SessionGrant],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Invalid refresh token",
            422: "Validation error",
            429: "Too many attempts",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_login)
async def refresh_session(
    request: Request,
    body: SessionRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SessionGrant]:
    """Ротация refresh-токена. Reuse detection и grace-окно те же, что в v1.

    Refresh приходит в теле запроса, поэтому `X-CSRF-Token` не требуется: CSRF
    защищает от браузерного автозапроса с cookie, а не от Bearer-клиента.
    """
    svc = AuthService(db)
    try:
        tokens, session = await svc.refresh_session(
            refresh_token_plain=body.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except AuthError as exc:
        raise to_problem(exc) from exc
    user = _session_of(await db.get(User, session.user_id), session)
    return _grant(request, user, tokens, session)


@router.post(
    "/2fa/challenges/verify",
    response_model=SuccessResponse[SessionGrant],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Invalid ticket or code",
            422: "Validation error",
            429: "Too many attempts",
            500: "Internal server error",
        }
    ),
)
@limiter.limit(settings.rate_limit_2fa_verify)
async def verify_2fa_challenge(
    request: Request,
    body: TwoFaChallengeRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[SessionGrant]:
    """Второй шаг входа: ticket + TOTP/recovery-код → grant с токенами в теле."""
    svc = AuthService(db)
    try:
        tokens, session = await svc.verify_2fa_session(
            body.ticket,
            body.code,
            request.headers.get("user-agent"),
            _client_ip(request),
            **_session_metadata(body),
        )
    except AuthError as exc:
        raise to_problem(exc) from exc
    user = _session_of(await db.get(User, session.user_id), session)
    return _grant(request, user, tokens, session)


@router.get(
    "/sessions",
    response_model=SuccessResponse[list[SessionSummary]],
    response_model_by_alias=True,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def list_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    session_id: uuid.UUID | None = Depends(get_current_session_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[list[SessionSummary]]:
    """Журнал активных сессий устройств; текущая помечена `current`."""
    rows = await AuthService(db).list_session_models(user, session_id)
    return SuccessResponse[list[SessionSummary]](
        data=[session_summary(row, current=row.id == session_id) for row in rows],
        meta=ResponseMeta(request_id=request_id_for(request)),
    )


@router.delete(
    "/sessions/current",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(
        {
            401: "Authentication required",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def revoke_current_session(
    request: Request,
    user: User = Depends(get_current_user),
    session_id: uuid.UUID | None = Depends(get_current_session_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Logout нативного клиента: отзыв сессии, по которой пришёл Bearer.

    Refresh в теле не нужен — «текущая» сессия однозначно определяется `sid` из
    access-JWT, который сервер всё равно проверил в get_current_user.
    """
    if session_id is None:
        raise V2ProblemError(
            code="AUTHENTICATION_REQUIRED",
            status=401,
            title="Требуется авторизация",
            detail="В access-токене нет идентификатора сессии",
        )
    await AuthService(db).revoke_session(user, session_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/sessions/{sessionId}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(
        {
            401: "Authentication required",
            404: "Session not found",
            422: "Validation error",
            500: "Internal server error",
        }
    ),
)
async def revoke_session(
    request: Request,
    session_id: uuid.UUID = Path(alias="sessionId"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Отзыв одной своей сессии (например, забытого устройства)."""
    revoked = await AuthService(db).revoke_session(user, session_id, None)
    if revoked is None:
        raise V2ProblemError(
            code="RESOURCE_NOT_FOUND",
            status=404,
            title="Ресурс не найден",
            detail="Сессия не найдена или уже отозвана",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
