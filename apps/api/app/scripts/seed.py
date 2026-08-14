"""Seed: создаёт аккаунт менеджера (idempotent).

Запуск: make seed  (внутри контейнера api: python -m app.scripts.seed)

Параметры через окружение:
  SEED_MANAGER_EMAIL     (по умолчанию manager@example.by)
  SEED_MANAGER_PASSWORD  (по умолчанию manager12345)
  SEED_MANAGER_NAME      (по умолчанию «Менеджер»)

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

EMAIL = os.environ.get("SEED_MANAGER_EMAIL", "manager@example.by")
PASSWORD = os.environ.get("SEED_MANAGER_PASSWORD", "manager12345")
NAME = os.environ.get("SEED_MANAGER_NAME", "Менеджер")


async def seed_manager() -> None:
    setup_logging()
    log = get_logger("app.scripts.seed")

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == EMAIL))
        if existing is not None:
            log.info("seed.manager.exists", email=EMAIL)
            return

        manager = User(
            email=EMAIL,
            password_hash=hash_password(PASSWORD),
            full_name=NAME,
            role=UserRole.MANAGER,
            is_active=True,
            consent_accepted_at=None,
        )
        db.add(manager)
        await db.commit()
        log.info("seed.manager.created", email=EMAIL, id=str(manager.id))
        # Печатаем в stdout для удобства первого запуска
        print(f"\n✅ Менеджер создан:\n   email:    {EMAIL}\n   пароль:   {PASSWORD}\n", flush=True)


def main() -> None:
    try:
        asyncio.run(seed_manager())
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ошибка seed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
