"""Seed: создаёт аккаунт менеджера (idempotent).

Запуск: make seed  (внутри контейнера api: python -m app.scripts.seed)

Параметры через окружение (обязательные, без значений по умолчанию):
  SEED_MANAGER_EMAIL     e-mail менеджера
  SEED_MANAGER_PASSWORD  пароль, минимум 12 символов
  SEED_MANAGER_NAME      (по умолчанию «Менеджер»)

Раньше здесь стояли дефолты manager@example.by / manager12345 — из-за них
`make seed` без настроек создавал одинаково известный аккаунт с правами
менеджера. Теперь скрипт требует явных кредов и печатает только e-mail.

См. ARCHITECTURE_PLAN.md §15 Этап 2 (seed-аккаунт менеджера).
"""
import asyncio
import os
import sys

from sqlalchemy import select

from app.core.logging import get_logger, setup_logging
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole
from app.models.user import User

NAME = os.environ.get("SEED_MANAGER_NAME", "Менеджер")
MIN_PASSWORD_LENGTH = 12

# Зарезервированные и special-use TLD (RFC 2606 / RFC 6761): email-validator
# отвергает их на входе, поэтому пользователь с таким адресом не сможет войти.
_RESERVED_EMAIL_DOMAINS = frozenset(
    {"test", "local", "invalid", "localhost", "example", "internal", "lan"}
)


def _read_credentials() -> tuple[str, str]:
    """Креды только из окружения: дефолтный менеджер с известным паролем —
    это готовая точка входа, а не удобство."""
    email = (os.environ.get("SEED_MANAGER_EMAIL") or "").strip()
    password = os.environ.get("SEED_MANAGER_PASSWORD") or ""
    if not email or "@" not in email:
        print(
            "❌ Задайте SEED_MANAGER_EMAIL (e-mail менеджера) и запустите seed снова.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(password) < MIN_PASSWORD_LENGTH:
        # Длина вместо сложности: у seed-пароля нет срока жизни, но быть
        # короче 12 символов — это уже не пароль.
        print(
            f"❌ SEED_MANAGER_PASSWORD короче {MIN_PASSWORD_LENGTH} символов.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Ловушка: адрес вида `manager@example.test` проходит superficальную
    # проверку «есть @», создаёт пользователя — и делает его неспособным войти
    # никогда: валидатор email на логине отвергает зарезервированные/special-use
    # TLD (.test, .local, .invalid…) и отвечает 422 вместо 401. Пользователь
    # видит «Не удалось войти» и не понимает почему. Ловим здесь, до создания.
    domain = email.rpartition("@")[2].lower()
    if not domain or domain in _RESERVED_EMAIL_DOMAINS:
        print(
            f"❌ Домен «{domain or '?'}» зарезервирован и не пройдёт проверку e-mail "
            "при входе — аккаунт будет создан, но войти не получится.\n"
            "   Возьмите обычный домен, например manager@example.com.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return email, password


async def seed_manager() -> None:
    setup_logging()
    log = get_logger("app.scripts.seed")
    email, password = _read_credentials()

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            log.info("seed.manager.exists", email=email)
            return

        manager = User(
            email=email,
            password_hash=hash_password(password),
            full_name=NAME,
            role=UserRole.MANAGER,
            is_active=True,
            consent_accepted_at=None,
        )
        db.add(manager)
        await db.commit()
        log.info("seed.manager.created", email=email, id=str(manager.id))
        # Пароль в вывод не попадает: логи и вывод seed'а часто пересылают.
        print(f"\n✅ Менеджер создан: {email}\n   Пароль задан в SEED_MANAGER_PASSWORD.\n", flush=True)


def main() -> None:
    try:
        asyncio.run(seed_manager())
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ошибка seed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
