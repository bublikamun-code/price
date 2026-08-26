"""Сервис аутентификации: login (в т.ч. ветка 2FA), refresh (rotation), logout,
2FA менеджера (фича H) и журнал сессий (фича I). См. ARCHITECTURE_PLAN.md §11, §16 п.22.

Модель токенов (см. ARCHITECTURE_PLAN.md §11, §16 фича I):
  - access  — короткий JWT (stateless), содержит sub=user_id, role, sid=session_id
  - refresh — opaque случайная строка; хранится в sessions как SHA-256 хэш.
              Позволяет: ротацию, отзыв, список активных сессий.
  - 2fa     — короткоживущий ticket (TTL 5 мин), выдаётся login'ом при включённой
              2FA вместо токенов; гасится в /auth/2fa/verify.

Сессии:
  - login  → создаётся новая session, клиенту выдаётся refresh (plain)
  - refresh→ старая session помечается revoked, создаётся новая (rotation)
  - logout → session помечается revoked
"""
import base64
import hashlib
import io
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import qrcode
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import (
    ConsentLog,
    PasswordResetToken,
    Session as SessionModel,
    TotpRecoveryCode,
    User,
)
from app.repositories import audit as audit_repo
from app.schemas.auth import (
    SessionOut,
    TokenPair,
    TwoFASetupOut,
    UserUpdate,
)
from app.services.cache import (
    clear_login_failures,
    invalidate_session,
    invalidate_tags,
    is_account_locked,
    record_login_failure,
    user_tag,
)

log = get_logger("app.services.auth")

# 2FA (§16 п.22): issuer otpauth-uri, число recovery-кодов и их формат.
# Recovery-код = secrets.token_hex(5) → ровно 10 hex-символов; TOTP — 6 цифр,
# форматы не пересекаются, что позволяет не гонять bcrypt по recovery-хэшам
# на каждой опечатке в TOTP-коде.
_TOTP_ISSUER = "PricePortal"
_RECOVERY_CODES_COUNT = 8
_RECOVERY_CODE_LEN = 10  # len(secrets.token_hex(5))
_TOTP_VALID_WINDOW = 1  # ±30 сек (§16 п.22)


def _hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _generate_refresh() -> str:
    return secrets.token_urlsafe(48)


def _generate_recovery_code() -> str:
    return secrets.token_hex(5)


def _is_recovery_format(code: str) -> bool:
    return len(code) == _RECOVERY_CODE_LEN and all(c in "0123456789abcdef" for c in code)


def _qr_png_data_url(otpauth_uri: str) -> str:
    """QR-код otpauth-uri → PNG → base64 data-url (для /profile/security)."""
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class AuthError(Exception):
    """Унифицированная ошибка аутентификации (→ 401 в роутере)."""


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------- login ----------
    async def login(
        self, email: str, password: str, user_agent: str | None, ip: str | None
    ) -> tuple[User, TokenPair | None]:
        """Проверяет креды. Возвращает (user, tokens).

        tokens=None → включена 2FA: сессия НЕ создаётся, роутер вместо токенов
        выдаёт короткоживущий ticket (§16 п.22).
        """
        # Блокировка аккаунта после N неудачных входов (H4): проверяем до
        # проверки кредов, чтобы брутфорс упирался в lockout, а не в rate-limit.
        if await is_account_locked(email, settings.login_max_attempts):
            log.warning("auth.login_locked", email=email, ip=ip)
            raise AuthError("Слишком много неудачных попыток. Попробуйте позже.")

        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            # одинаковая ошибка чтобы не светить существование email;
            # счётчик не трогаем — иначе атакующий лочил бы произвольные email
            raise AuthError("Неверный email или пароль")
        if not verify_password(password, user.password_hash):
            attempts = await record_login_failure(
                email, settings.login_max_attempts, settings.login_lockout_minutes
            )
            log.warning(
                "auth.login_failed", user_id=str(user.id), attempts=attempts, ip=ip
            )
            raise AuthError("Неверный email или пароль")

        # успешный вход сбрасывает счётчик неудач
        await clear_login_failures(email)

        if user.totp_secret is not None:
            log.info("auth.login_2fa_required", user_id=str(user.id), ip=ip)
            return user, None

        token_pair = await self._issue_new_session(user, user_agent, ip)
        log.info("auth.login", user_id=str(user.id), ip=ip)
        return user, token_pair

    # ---------- refresh (rotation) ----------
    async def refresh(
        self, refresh_token_plain: str, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        token_hash = _hash_token(refresh_token_plain)
        session = await self.db.scalar(
            select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        )
        if session is None or session.revoked:
            raise AuthError("Недействительный refresh-токен")
        if session.expires_at <= datetime.now(timezone.utc):
            raise AuthError("Срок действия refresh-токена истёк")

        # M4: привязка к клиенту. Смена user-agent — сильный сигнал кражи токена
        # (другой браузер/устройство) → отказ. Смена IP лишь логируем: у мобильных
        # клиентов адрес меняется, жёсткий reject ломал бы легитимные сессии.
        if session.user_agent and user_agent and session.user_agent != user_agent:
            log.warning(
                "auth.refresh_ua_mismatch", user_id=str(session.user_id),
                sid=str(session.id), ip=ip,
            )
            raise AuthError("Недействительный refresh-токен")
        if session.ip and ip and session.ip != ip:
            log.warning(
                "auth.refresh_ip_changed", user_id=str(session.user_id),
                sid=str(session.id), from_ip=session.ip, ip=ip,
            )

        user = await self.db.get(User, session.user_id)
        if user is None or not user.is_active:
            raise AuthError("Пользователь неактивен")

        # ротация: отзываем старую, создаём новую
        session.revoked = True
        old_sid = session.id
        token_pair = await self._issue_new_session(user, user_agent, ip)
        await invalidate_session(old_sid)
        log.info("auth.refresh", user_id=str(user.id), old_sid=str(old_sid))
        return token_pair

    # ---------- logout ----------
    async def logout(self, refresh_token_plain: str | None) -> None:
        if not refresh_token_plain:
            return
        token_hash = _hash_token(refresh_token_plain)
        session = await self.db.scalar(
            select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        )
        if session is not None and not session.revoked:
            session.revoked = True
            await self.db.commit()
            await invalidate_session(session.id)
            log.info("auth.logout", sid=str(session.id))

    # ---------- update profile (PATCH /auth/me, §6 / §20.4 / §16 п.20-6) ----------
    async def update_profile(
        self,
        user: User,
        updates: UserUpdate,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        """Частичное обновление профиля: применяются только явно заданные поля.

        ``null`` в значении трактуется как «поле не задано» (все поля Optional),
        поэтому не затирает прежнее значение в БД.

        Согласие (§16 п.20-6): ``consent_accepted=True`` фиксируется в consent_log
        (ip + user-agent, идемпотентно — повторная отправка не плодит записи);
        ``False`` (отзыв) через API запрещён → 422.
        """
        if updates.consent_accepted is False:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Согласие нельзя отозвать через API",
            )
        # consent_accepted обрабатывается отдельно — на User нет такого поля
        changed = {
            k: v
            for k, v in updates.model_dump(exclude_unset=True).items()
            if v is not None and k != "consent_accepted"
        }
        if updates.consent_accepted is True and user.consent_accepted_at is None:
            accepted_at = datetime.now(timezone.utc)
            user.consent_accepted_at = accepted_at
            self.db.add(
                ConsentLog(
                    user_id=user.id,
                    policy_version="1.0",
                    ip=ip,
                    user_agent=(user_agent or "")[:512] or None,
                    accepted_at=accepted_at,
                )
            )
            log.info("auth.consent_accepted", user_id=str(user.id), ip=ip)
        # M5: whitelist полей — setattr только по явно разрешённым колонкам User,
        # чтобы расширение схемы не позволило трогать role/is_active/password_hash.
        allowed = {"display_currency", "price_digest_enabled", "price_digest_sources"}
        # Клиент видит цены только в BYN: присланное display_currency игнорируется
        # (MANAGER может выбирать валюту как раньше).
        if user.role == UserRole.CLIENT:
            changed.pop("display_currency", None)
        for field, value in changed.items():
            if field in allowed:
                setattr(user, field, value)
        await self.db.commit()
        if "display_currency" in changed:
            await invalidate_tags(user_tag(user.id))
        logged_fields = list(changed) + (["consent_accepted"] if updates.consent_accepted else [])
        log.info("auth.update_profile", user_id=str(user.id), fields=",".join(logged_fields))
        return user

    # ---------- 2FA (фича H, §16 п.22; только MANAGER — RBAC в роутере) ----------
    def setup_2fa(self, user: User) -> TwoFASetupOut:
        """Генерирует TOTP-секрет + otpauth-uri + QR. Ничего не сохраняет:
        секрет сохраняется только в /2fa/enable после подтверждения кодом."""
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=_TOTP_ISSUER)
        return TwoFASetupOut(
            secret=secret,
            otpauth_uri=uri,
            qr_png_data_url=_qr_png_data_url(uri),
        )

    async def enable_2fa(self, user: User, secret: str, code: str) -> list[str]:
        """Подтверждает и сохраняет totp_secret, выдаёт recovery-коды (plaintext 1 раз)."""
        if not pyotp.TOTP(secret).verify(code, valid_window=_TOTP_VALID_WINDOW):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код подтверждения",
            )
        user.totp_secret = secret
        # повторный enable = ротация: старые recovery-коды заменяются новыми
        for old in await self.db.scalars(
            select(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id)
        ):
            await self.db.delete(old)
        codes = [_generate_recovery_code() for _ in range(_RECOVERY_CODES_COUNT)]
        for plain in codes:
            self.db.add(
                TotpRecoveryCode(user_id=user.id, code_hash=hash_password(plain), used_at=None)
            )
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="user.2fa.enable",
            target_type="user",
            target_id=user.id,
        )
        await self.db.commit()
        log.info("auth.2fa_enabled", user_id=str(user.id))
        return codes

    async def verify_2fa(
        self, ticket: str, code: str, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        """Второй шаг логина: ticket + TOTP/recovery → обычные токены+сессия."""
        user = await self._decode_2fa_ticket(ticket)
        if not self._check_totp(user, code) and not await self._try_use_recovery(user, code):
            raise AuthError("Неверный код")
        token_pair = await self._issue_new_session(user, user_agent, ip)
        log.info("auth.login_2fa_completed", user_id=str(user.id), ip=ip)
        return token_pair

    async def disable_2fa(self, user: User, code: str | None, password: str | None) -> None:
        """Отключение 2FA: подтверждение TOTP/recovery-кодом ИЛИ паролем."""
        confirmed = (
            code is not None
            and (self._check_totp(user, code) or await self._try_use_recovery(user, code, commit=False))
        ) or (password is not None and verify_password(password, user.password_hash))
        if not confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код или пароль",
            )
        user.totp_secret = None
        for rc in await self.db.scalars(
            select(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id)
        ):
            await self.db.delete(rc)
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="user.2fa.disable",
            target_type="user",
            target_id=user.id,
        )
        await self.db.commit()
        log.info("auth.2fa_disabled", user_id=str(user.id))

    async def _decode_2fa_ticket(self, ticket: str) -> User:
        """Декодирует 2fa-ticket и возвращает активного пользователя.

        Просроченный/поддельный ticket, а также access/refresh-токен вместо
        ticket (несовпадение type) → AuthError → 401 в роутере.
        """
        try:
            payload = decode_token(ticket)
        except jwt.PyJWTError as exc:
            raise AuthError("Недействительный ticket") from exc
        if payload.get("type") != "2fa":
            raise AuthError("Недействительный ticket")
        try:
            user_id = uuid.UUID(str(payload.get("sub")))
        except (ValueError, TypeError) as exc:
            raise AuthError("Недействительный ticket") from exc
        user = await self.db.get(User, user_id)
        if user is None or not user.is_active:
            raise AuthError("Недействительный ticket")
        return user

    def _check_totp(self, user: User, code: str) -> bool:
        if user.totp_secret is None:
            return False
        return pyotp.TOTP(user.totp_secret).verify(code.strip(), valid_window=_TOTP_VALID_WINDOW)

    async def _try_use_recovery(self, user: User, code: str, *, commit: bool = True) -> bool:
        """Пытается списать recovery-код (неиспользованный). Совпадение → used_at.

        Формат recovery (10 hex) не пересекается с TOTP (6 цифр) — для «не того»
        формата bcrypt-проверки не выполняются вовсе.
        """
        normalized = code.strip().lower()
        if not _is_recovery_format(normalized):
            return False
        unused = await self.db.scalars(
            select(TotpRecoveryCode).where(
                TotpRecoveryCode.user_id == user.id,
                TotpRecoveryCode.used_at.is_(None),
            )
        )
        for rc in unused:
            if verify_password(normalized, rc.code_hash):
                rc.used_at = datetime.now(timezone.utc)
                if commit:
                    await self.db.commit()
                log.info("auth.2fa_recovery_used", user_id=str(user.id))
                return True
        return False

    # ---------- Журнал сессий (фича I, §16 п.22; обе роли) ----------
    async def list_sessions(self, user: User, current_refresh_plain: str | None) -> list[SessionOut]:
        """Активные (не revoked, не истёкшие) сессии пользователя, новые сверху."""
        now = datetime.now(timezone.utc)
        current_hash = _hash_token(current_refresh_plain) if current_refresh_plain else None
        sessions = await self.db.scalars(
            select(SessionModel)
            .where(
                SessionModel.user_id == user.id,
                SessionModel.revoked.is_(False),
                SessionModel.expires_at > now,
            )
            .order_by(SessionModel.created_at.desc())
        )
        return [
            SessionOut(
                id=s.id,
                user_agent=s.user_agent,
                ip=s.ip,
                created_at=s.created_at,
                expires_at=s.expires_at,
                current=current_hash is not None and s.refresh_token_hash == current_hash,
            )
            for s in sessions
        ]

    async def revoke_session(
        self, user: User, session_id: uuid.UUID, current_refresh_plain: str | None
    ) -> bool | None:
        """Отзыв своей сессии. None → не найдена/чужая (роутер отдаст 404).

        Возвращает True, если отозвана текущая (по refresh-куке) — роутер
        дополнительно чистит auth-куки.
        """
        session = await self.db.get(SessionModel, session_id)
        if session is None or session.user_id != user.id or session.revoked:
            return None
        session.revoked = True
        await self.db.commit()
        await invalidate_session(session.id)
        current_hash = _hash_token(current_refresh_plain) if current_refresh_plain else None
        is_current = current_hash is not None and session.refresh_token_hash == current_hash
        log.info("auth.session_revoked", user_id=str(user.id), sid=str(session.id), current=is_current)
        return is_current

    async def revoke_all_sessions(self, user: User, current_refresh_plain: str | None) -> int:
        """Отзыв всех своих активных сессий кроме текущей. Возвращает число отозванных."""
        now = datetime.now(timezone.utc)
        current_hash = _hash_token(current_refresh_plain) if current_refresh_plain else None
        sessions = await self.db.scalars(
            select(SessionModel).where(
                SessionModel.user_id == user.id,
                SessionModel.revoked.is_(False),
                SessionModel.expires_at > now,
            )
        )
        revoked = 0
        revoked_sids: list[uuid.UUID] = []
        for s in sessions:
            if current_hash is not None and s.refresh_token_hash == current_hash:
                continue
            s.revoked = True
            revoked_sids.append(s.id)
            revoked += 1
        await self.db.commit()
        for sid in revoked_sids:
            await invalidate_session(sid)
        log.info("auth.sessions_revoked_all", user_id=str(user.id), count=revoked)
        return revoked

    # ---------- внутреннее: создание сессии + токенов ----------
    async def _issue_new_session(
        self, user: User, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        refresh_plain = _generate_refresh()
        session = SessionModel(
            user_id=user.id,
            refresh_token_hash=_hash_token(refresh_plain),
            user_agent=(user_agent or "")[:512] or None,
            ip=ip,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_ttl_days),
            revoked=False,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        access = create_access_token(
            subject=str(user.id),
            extra={"role": user.role.value, "sid": str(session.id)},
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh_plain,
            expires_in=settings.access_token_ttl_min * 60,
        )

    # ---------- Сброс пароля по email (forgot/reset) ----------
    @staticmethod
    def _hash_reset_token(token: str) -> str:
        """SHA-256 хэш токена сброса: plaintext хранится только в письме."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def request_password_reset(self, email: str) -> str | None:
        """Создать одноразовый токен сброса (TTL 30 мин). None → аккаунта нет/неактивен.

        Возвращает plaintext-токен для ссылки в письме; роутер всегда отвечает 202,
        независимо от того, существует ли аккаунт.
        """
        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            return None
        plain = secrets.token_urlsafe(32)
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=self._hash_reset_token(plain),
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.password_reset_ttl_min),
            )
        )
        await self.db.commit()
        log.info("auth.password_reset_requested", user_id=str(user.id))
        return plain

    async def reset_password(self, token: str, new_password: str) -> bool:
        """Смена пароля по токену. False → токен неизвестен/использован/истёк.

        Помечает токен used_at и инвалидирует ВСЕ refresh-сессии пользователя
        (как reset-password у менеджера, §16 п.19).
        """
        prt = await self.db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == self._hash_reset_token(token)
            )
        )
        now = datetime.now(timezone.utc)
        if prt is None or prt.used_at is not None or prt.expires_at < now:
            return False
        user = await self.db.get(User, prt.user_id)
        if user is None or not user.is_active:
            return False
        user.password_hash = hash_password(new_password)
        prt.used_at = now
        # revoke_all_sessions коммитит транзакцию целиком и инвалидирует сессии.
        await self.revoke_all_sessions(user, current_refresh_plain=None)
        log.info("auth.password_reset_done", user_id=str(user.id))
        return True
