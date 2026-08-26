"""Роутер аутентификации. См. ARCHITECTURE_PLAN.md §6, §16 п.22 (2FA + сессии)."""
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, require_role, validate_csrf
from app.core.limiter import limiter
from app.core.security import create_2fa_ticket
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    SessionListResponse,
    TelegramLinkCodeOut,
    TokenPair,
    TwoFADisableRequest,
    TwoFAEnableRequest,
    TwoFAEnableResponse,
    TwoFASetupResponse,
    TwoFAVerifyRequest,
    UserPublic,
    UserUpdate,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.services.auth import AuthError, AuthService
from app.services.email import build_password_reset_email, queue_email
from app.services.telegram_auth import generate_link_code

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, tokens: TokenPair) -> None:
    secure = settings.cookie_secure  # prod: только HTTPS-куки (COOKIE_SECURE, §16 п.30)
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


def _clear_auth_cookies(response: Response) -> None:
    # Тот же флаг, что при установке: иначе браузер не удалит Secure-куку (§16 п.30)
    secure = settings.cookie_secure
    response.delete_cookie("access_token", path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie("refresh_token", path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(
        settings.csrf_cookie_name, path="/", secure=secure, httponly=False, samesite="lax"
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
    """Вход по email+паролю. Access и refresh также проставляются в httpOnly cookies.

    При включённой 2FA (§16 п.22) токены не выдаются и сессия не создаётся:
    возвращается ticket для POST /auth/2fa/verify.
    """
    svc = AuthService(db)
    try:
        user, tokens = await svc.login(
            email=body.email,
            password=body.password,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except AuthError as exc:
        # Неуспешный логин чистит остаточные стейл-куки (§16 п.21). Возвращаем
        # JSONResponse, а не raise: куки с injected Response теряются при HTTPException.
        error_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)}
        )
        _clear_auth_cookies(error_response)
        return error_response
    if tokens is None:
        # 2FA: без кук и без сессии — только короткоживущий ticket (§16 п.22).
        # JSONResponse минует response_model=TokenPair — формат ответа другой.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "data": {
                    "two_fa_required": True,
                    "ticket": create_2fa_ticket(str(user.id)),
                }
            },
        )
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
    _clear_auth_cookies(response)


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


# =========================================================
# 2FA (фича H, §16 п.22; только MANAGER, кроме verify)
# =========================================================
@router.post("/2fa/setup", response_model=TwoFASetupResponse)
async def setup_2fa(
    current_user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> TwoFASetupResponse:
    """Сгенерировать TOTP-секрет + QR (без сохранения).

    Секрет сохраняется только в /2fa/enable после подтверждения кодом из приложения.
    """
    svc = AuthService(db)
    return TwoFASetupResponse(data=svc.setup_2fa(current_user))


@router.post("/2fa/enable", response_model=TwoFAEnableResponse)
async def enable_2fa(
    body: TwoFAEnableRequest,
    current_user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> TwoFAEnableResponse:
    """Включить 2FA: {secret, code} → recovery-коды (plaintext показывается 1 раз)."""
    svc = AuthService(db)
    codes = await svc.enable_2fa(current_user, body.secret, body.code)
    return TwoFAEnableResponse(data={"recovery_codes": codes})


@router.post("/2fa/verify", response_model=TokenPair)
@limiter.limit(settings.rate_limit_2fa_verify)
async def verify_2fa(
    body: TwoFAVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Второй шаг логина при 2FA: ticket + TOTP/recovery-код → токены+куки+сессия.

    Неаутентифицированный запрос с данными в теле — освобождён от CSRF
    (как login, §16 п.21-22). Провал чистит остаточные стейл-куки.
    """
    svc = AuthService(db)
    try:
        tokens = await svc.verify_2fa(
            ticket=body.ticket,
            code=body.code,
            user_agent=request.headers.get("user-agent"),
            ip=_client_ip(request),
        )
    except AuthError as exc:
        error_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)}
        )
        _clear_auth_cookies(error_response)
        return error_response
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_2fa(
    body: TwoFADisableRequest,
    current_user: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Отключить 2FA: подтверждение кодом (TOTP/recovery) или паролем."""
    svc = AuthService(db)
    await svc.disable_2fa(current_user, code=body.code, password=body.password)


# =========================================================
# Журнал сессий (фича I, §16 п.22; обе роли)
# =========================================================
@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    """Свои активные сессии (не revoked/expired), новые сверху.

    ``current`` — сессия, чей refresh-хэш совпадает с текущей refresh-кукой.
    """
    svc = AuthService(db)
    items = await svc.list_sessions(current_user, request.cookies.get("refresh_token"))
    return SessionListResponse(data=items)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Отзыв своей сессии (чужая → 404); текущая — дополнительно с очисткой кук."""
    svc = AuthService(db)
    result = await svc.revoke_session(
        current_user, session_id, request.cookies.get("refresh_token")
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    if result:
        _clear_auth_cookies(response)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Отзыв всех своих активных сессий кроме текущей."""
    svc = AuthService(db)
    await svc.revoke_all_sessions(current_user, request.cookies.get("refresh_token"))


@router.post("/telegram/link-code", response_model=TelegramLinkCodeOut)
async def telegram_link_code(
    current_user: User = Depends(get_current_user),
) -> TelegramLinkCodeOut:
    """Одноразовый код связки Telegram для Mini App (§16 п.27).

    Только CLIENT: m-app — клиентский путь, менеджерский линк запрещён.
    """
    if current_user.role != UserRole.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Связка Telegram доступна только клиентам",
        )
    return TelegramLinkCodeOut(**generate_link_code(current_user.id))


# =========================================================
# Восстановление пароля по email (forgot/reset)
# =========================================================
@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit_forgot_password)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Запрос сброса пароля. Всегда 202 — существование аккаунта не раскрываем.

    Если активный CLIENT/MANAGER/ADMIN существует — создаётся одноразовый
    токен (30 мин) и ставится в очередь письмо со ссылкой на /reset-password.
    Письмо fire-and-forget: ошибка отправки не влияет на ответ.
    """
    svc = AuthService(db)
    plain = await svc.request_password_reset(body.email)
    if plain is not None:
        base = settings.web_app_url.rstrip("/") if settings.web_app_url else ""
        link = f"{base}/reset-password?token={plain}" if base else f"/reset-password?token={plain}"
        subject, html_body = build_password_reset_email(link)
        queue_email(to=body.email, subject=subject, html_body=html_body)
    return {"detail": "Если аккаунт существует, письмо со ссылкой отправлено"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Сброс пароля по токену из письма: смена hash + инвалидация всех refresh-сессий.

    Токен неизвестен/использован/истёк → 400 (без раскрытия лишних деталей).
    """
    svc = AuthService(db)
    ok = await svc.reset_password(body.token, body.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка недействительна или устарела",
        )
    return {"detail": "Пароль изменён"}
