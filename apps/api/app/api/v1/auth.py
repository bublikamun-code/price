"""Роутер аутентификации. См. ARCHITECTURE_PLAN.md §6."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, validate_csrf
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenPair, UserPublic, UserUpdate
from app.services.auth import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, tokens: TokenPair) -> None:
    secure = settings.env != "dev"  # в dev HTTP → Secure=False
    response.set_cookie(
        "access_token", tokens.access_token,
        max_age=settings.access_token_ttl_min * 60,
        httponly=True, secure=secure, samesite="lax", path="/",
    )
    response.set_cookie(
        "refresh_token", tokens.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True, secure=secure, samesite="lax", path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name, secrets.token_urlsafe(32),
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=False, secure=secure, samesite="lax", path="/",
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenPair)
@limiter.limit(settings.rate_limit_login)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Вход по email+паролю. Access и refresh также проставляются в httpOnly cookies."""
    svc = AuthService(db)
    try:
        _, tokens = await svc.login(
            email=body.email,
            password=body.password,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(validate_csrf)])
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Обновление токенов (rotation). Refresh берётся только из httpOnly cookie."""
    refresh_plain = request.cookies.get("refresh_token")
    if not refresh_plain:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Нет refresh-токена")
    svc = AuthService(db)
    try:
        tokens = await svc.refresh(
            refresh_token_plain=refresh_plain,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_auth_cookies(response, tokens)
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(validate_csrf)],
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Отзыв текущей сессии и удаление auth cookies из браузера."""
    refresh_plain = request.cookies.get("refresh_token")
    svc = AuthService(db)
    await svc.logout(refresh_plain)
    secure = settings.env != "dev"
    response.delete_cookie("access_token", path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie("refresh_token", path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(
        settings.csrf_cookie_name, path="/", secure=secure, httponly=False, samesite="lax"
    )


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    """Текущий пользователь."""
    return UserPublic.from_user(current_user)


@router.patch("/me", response_model=UserPublic)
async def update_me(
    body: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPublic:
    """Частичное обновление профиля (§6): display_currency, настройки дайджеста цен (§20.4),
    принятие согласия на обработку ПДн (§16 п.20-6, фиксируется в consent_log с ip/user-agent).

    Доступно любому авторизованному (client/manager); применяются только заданные поля.
    """
    svc = AuthService(db)
    user = await svc.update_profile(
        current_user,
        body,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return UserPublic.from_user(user)
