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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.pricing import ExchangeRate
from app.models.user import (
    ConsentLog,
    PasswordResetToken,
    TotpRecoveryCode,
    User,
)
from app.models.user import (
    Session as SessionModel,
)
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.schemas.auth import (
    MyTermsBrandDiscount,
    MyTermsFixedRate,
    MyTermsOut,
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
# Grace-окно ротации refresh (аудит P0-1): максимум «догоняющих» переходов
# по цепочке ротаций за один запрос — защита от патологических циклов.
_MAX_GRACE_HOPS = 8


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
    """Унифицированная ошибка аутентификации (→ 401 в роутере).

    `code`/`status_code` нужны v2-адаптеру: нативный клиент различает
    «неверный пароль» и «аккаунт заблокирован» по problem code, а не по тексту.
    V1-роутер по-прежнему ловит AuthError и всегда отвечает 401.
    """

    code = "INVALID_CREDENTIALS"
    status_code = 401
    title = "Ошибка аутентификации"


class AuthLockedError(AuthError):
    """Брутфорс: email+IP исчерпал login_max_attempts."""

    code = "RATE_LIMITED"
    status_code = 429
    title = "Вход временно заблокирован"


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
        user, tokens, _session = await self.login_session(
            email, password, user_agent, ip
        )
        return user, tokens

    async def login_session(
        self,
        email: str,
        password: str,
        user_agent: str | None,
        ip: str | None,
        **session_metadata: str | None,
    ) -> tuple[User, TokenPair | None, SessionModel | None]:
        """Как login, но возвращает и созданную сессию — нужно v2-адаптеру
        нативного grant (§16 п.36), который обязан отдать `session.id` в теле.

        Сессия создаётся ровно одна: metadata передаётся в _issue_session, а не
        добавляется вторым вызовом поверх уже выданных токенов.
        """
        # Блокировка после N неудачных входов с пары email+IP (H4, P2 §3.1):
        # проверяем до проверки кредов, чтобы брутфорс упирался в lockout,
        # а не в rate-limit. Ключ с IP — чтобы атакующий не лочил чужие аккаунты.
        if await is_account_locked(email, settings.login_max_attempts, ip):
            log.warning("auth.login_locked", email=email, ip=ip)
            raise AuthLockedError("Слишком много неудачных попыток. Попробуйте позже.")

        user = await self.db.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active:
            # одинаковая ошибка чтобы не светить существование email;
            # счётчик не трогаем — иначе атакующий лочил бы произвольные email
            raise AuthError("Неверный email или пароль")
        if not verify_password(password, user.password_hash):
            attempts = await record_login_failure(
                email, settings.login_max_attempts, settings.login_lockout_minutes, ip
            )
            log.warning(
                "auth.login_failed", user_id=str(user.id), attempts=attempts, ip=ip
            )
            raise AuthError("Неверный email или пароль")

        # успешный вход сбрасывает счётчик неудач
        await clear_login_failures(email, ip)

        if user.totp_secret is not None:
            log.info("auth.login_2fa_required", user_id=str(user.id), ip=ip)
            return user, None, None

        token_pair, session = await self._issue_session(
            user, _generate_refresh(), user_agent, ip, **session_metadata
        )
        log.info("auth.login", user_id=str(user.id), ip=ip)
        return user, token_pair, session

    # ---------- refresh (rotation + grace-окно) ----------
    async def refresh(
        self, refresh_token_plain: str, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        token_pair, _session = await self.refresh_session(
            refresh_token_plain, user_agent, ip
        )
        return token_pair

    async def refresh_session(
        self, refresh_token_plain: str, user_agent: str | None, ip: str | None
    ) -> tuple[TokenPair, SessionModel]:
        token_hash = _hash_token(refresh_token_plain)
        session = await self.db.scalar(
            select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
        )
        if session is None:
            raise AuthError("Недействительный refresh-токен")

        # Grace-окно (аудит P0-1): параллельные refresh (несколько вкладок/воркеров
        # фронта) могут прислать уже ротированный токен. В пределах
        # settings.refresh_grace_seconds старый токен «догоняет» цепочку ротаций
        # до актуальной сессии, и ротация продолжается от неё; после окна — 401
        # (reuse-detection сохранён: logout/revoke-сессии имеют rotated_at=NULL).
        session = await self._resolve_rotation_grace(session, ip=ip)

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

        # ротация: отзываем старую (с пометкой grace), создаём новую.
        # Новый refresh генерируем заранее: hash старой сессии указывает на
        # актуальный токен атомарно (одним commit), без окна «revoked, но без
        # ссылки на преемника».
        old_sid = session.id
        now = datetime.now(timezone.utc)
        session.revoked = True
        session.rotated_at = now
        new_refresh_plain = _generate_refresh()
        session.superseded_by_hash = _hash_token(new_refresh_plain)
        await self.db.commit()
        token_pair, new_session = await self._issue_session(
            user, new_refresh_plain, user_agent, ip
        )
        await invalidate_session(old_sid)
        log.info("auth.refresh", user_id=str(user.id), old_sid=str(old_sid))
        return token_pair, new_session

    async def _resolve_rotation_grace(self, session: SessionModel, *, ip: str | None) -> SessionModel:
        """Если сессия отозвана ротацией в пределах grace-окна — идём по цепочке
        superseded_by_hash до актуальной (не отозванной) сессии. Иначе AuthError.
        """
        hops = 0
        while session.revoked:
            in_grace = (
                session.rotated_at is not None
                and session.superseded_by_hash is not None
                and datetime.now(timezone.utc) - session.rotated_at
                <= timedelta(seconds=settings.refresh_grace_seconds)
            )
            if not in_grace or hops >= _MAX_GRACE_HOPS:
                raise AuthError("Недействительный refresh-токен")
            successor = await self.db.scalar(
                select(SessionModel).where(
                    SessionModel.refresh_token_hash == session.superseded_by_hash
                )
            )
            if successor is None:
                raise AuthError("Недействительный refresh-токен")
            log.info(
                "auth.refresh_grace", user_id=str(session.user_id),
                sid=str(session.id), successor_sid=str(successor.id), ip=ip,
            )
            session = successor
            hops += 1
        return session

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

    # ---------- мои условия (GET /auth/my-terms, SITEMAP §6 /profile) ----------
    async def my_terms(self, user: User) -> MyTermsOut:
        """Персональные условия клиента: скидки по брендам + фикс. курс договора.

        Скидки — вся матрица (без записи = 0, как в менеджерской карточке
        клиента); fixed_rate — курс по договору (users.fixed_rate_id), если
        менеджер его зафиксировал.
        """
        rows = await users_repo.fetch_discount_rows(self.db, user_id=user.id)
        fixed_rate = None
        if user.fixed_rate_id is not None:
            rate = await self.db.get(ExchangeRate, user.fixed_rate_id)
            if rate is not None:
                fixed_rate = MyTermsFixedRate(
                    currency=rate.currency_code,
                    rate=float(rate.rate),
                    source=rate.source,
                    fetched_at=datetime.combine(
                        rate.fetched_at, datetime.min.time(), tzinfo=timezone.utc
                    ),
                )
        return MyTermsOut(
            discounts=[
                MyTermsBrandDiscount(
                    brand_id=row.brand_id,
                    brand_name=row.brand_name,
                    discount_percent=float(row.percent),
                )
                for row in rows
            ],
            fixed_rate=fixed_rate,
        )

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
        # display_currency ∈ {BYN, USD, EUR, RUB} — выбор клиента (§8, уровень 2).
        allowed = {"display_currency", "price_digest_enabled", "price_digest_sources"}
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
        token_pair, _session = await self.verify_2fa_session(
            ticket, code, user_agent, ip
        )
        return token_pair

    async def verify_2fa_session(
        self,
        ticket: str,
        code: str,
        user_agent: str | None,
        ip: str | None,
        **session_metadata: str | None,
    ) -> tuple[TokenPair, SessionModel]:
        """Как verify_2fa, но возвращает и созданную сессию — нужно v2-адаптеру
        нативного второго шага (POST /api/v2/auth/2fa/challenges/verify)."""
        user = await self._decode_2fa_ticket(ticket)
        if not self._check_totp(user, code) and not await self._try_use_recovery(user, code):
            raise AuthError("Неверный код")
        token_pair, session = await self._issue_session(
            user, _generate_refresh(), user_agent, ip, **session_metadata
        )
        log.info("auth.login_2fa_completed", user_id=str(user.id), ip=ip)
        return token_pair, session

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
    async def list_session_models(
        self, user: User, current_session_id: uuid.UUID | None
    ) -> list[SessionModel]:
        """Активные сессии пользователя + флаг «эта текущая».

        Нативному клиенту нужен не только факт входа, но и устройство
        (`deviceName`/`os`/`appVersion`, §16 п.36), поэтому отдаём модели, а не
        v1-проекцию SessionOut. «Текущая» определяется по `sid` из access-JWT:
        у Bearer-клиента нет refresh-куки, по которой считал бы v1.
        """
        now = datetime.now(timezone.utc)
        sessions = await self.db.scalars(
            select(SessionModel)
            .where(
                SessionModel.user_id == user.id,
                SessionModel.revoked.is_(False),
                SessionModel.expires_at > now,
            )
            .order_by(SessionModel.created_at.desc())
        )
        return list(sessions)

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
    async def login_miniapp(
        self, user: User, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        """Вход из Telegram Mini App: подпись initData проверена роутером.

        2FA не запрашивается — подписанные Telegram initData являются фактором
        владения аккаунтом (§16 п.27).
        """
        token_pair, _session = await self._issue_session(
            user, _generate_refresh(), user_agent, ip
        )
        log.info("auth.login_miniapp", user_id=str(user.id), ip=ip)
        return token_pair

    async def _issue_session(
        self,
        user: User,
        refresh_plain: str,
        user_agent: str | None,
        ip: str | None,
        *,
        client_type: str | None = None,
        device_name: str | None = None,
        os_name: str | None = None,
        app_version: str | None = None,
    ) -> tuple[TokenPair, SessionModel]:
        """Создаёт сессию по уже сгенерированному refresh-токену (plain) и
        возвращает пару токенов вместе с созданной сессией. refresh() генерирует
        токен заранее — hash преемника записывается в старую сессию атомарно
        (см. grace-окно).

        Native-метаданные (§16 п.36) пишутся только когда они переданы: web-входы
        оставляют их NULL, поэтому в журнале сессий не появляется «пустых» строк.
        """
        session = SessionModel(
            user_id=user.id,
            refresh_token_hash=_hash_token(refresh_plain),
            user_agent=(user_agent or "")[:512] or None,
            ip=ip,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_ttl_days),
            revoked=False,
            client_type=client_type,
            device_name=(device_name or "")[:128] or None,
            os_name=(os_name or "")[:64] or None,
            app_version=(app_version or "")[:32] or None,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        access = create_access_token(
            subject=str(user.id),
            extra={"role": user.role.value, "sid": str(session.id)},
        )
        return (
            TokenPair(
                access_token=access,
                refresh_token=refresh_plain,
                expires_in=settings.access_token_ttl_min * 60,
                force_password_change=bool(user.must_change_password),
            ),
            session,
        )

    async def issue_session(
        self,
        user: User,
        refresh_plain: str,
        user_agent: str | None,
        ip: str | None,
        **session_metadata: str | None,
    ) -> tuple[TokenPair, SessionModel]:
        """Публичная обёртка над _issue_session для нативных клиентов.

        Нужна v2-адаптеру: ответ POST /api/v2/auth/sessions обязан вернуть id и
        createdAt созданной сессии, а v1-контракт этого не требует.
        """
        return await self._issue_session(
            user, refresh_plain, user_agent, ip, **session_metadata
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
        now = datetime.now(timezone.utc)
        # Старые неиспользованные ссылки должны перестать работать уже при
        # выдаче новой; обе операции коммитятся одной транзакцией сессии.
        await self.db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .values(used_at=now)
        )
        plain = secrets.token_urlsafe(32)
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=self._hash_reset_token(plain),
                expires_at=now
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

    # ---------- Смена пароля залогиненным (POST /auth/change-password) ----------
    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
        *,
        current_refresh_plain: str | None = None,
    ) -> None:
        """Смена текущего (временного) пароля залогиненным пользователем.

        Проверяет current_password (bcrypt), снимает флаг must_change_password
        (§16 п.19: после смены временного пароля фронт ведёт в кабинет) и
        инвалидирует все ДРУГИЕ refresh-сессии (текущая — по refresh-куке —
        выживает, чтобы не разлогинить только что сменившего пароль).
        Ошибки: HTTPException 400 (неверный текущий пароль).
        """
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный текущий пароль",
            )
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        # revoke_all_sessions коммитит и чистит кэш сессий; текущая сессия
        # (совпадает refresh-хэш с кукой) не трогается.
        revoked = await self.revoke_all_sessions(user, current_refresh_plain=current_refresh_plain)
        log.info(
            "auth.password_changed", user_id=str(user.id), other_sessions_revoked=revoked
        )
