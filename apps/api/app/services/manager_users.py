"""Сервис менеджер-панели: клиенты (создание, профиль, скидки, фикс-курс).

См. ARCHITECTURE_PLAN.md §6 (manager/users), §16 п.19.
Коммит выполняет сервис; аудит — через repositories/audit.py.
Ошибки: NotFoundError → 404, ConflictError → 409, обычный ValueError → 422.
"""
import secrets
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.pricing import ExchangeRate
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import notifications as notif_repo
from app.repositories import rates as rates_repo
from app.repositories import users as users_repo
from app.schemas.currency import RateOut
from app.schemas.manager_users import (
    ClientCreateIn,
    DiscountOut,
    DiscountsIn,
    FixedRateIn,
    UserPatchIn,
    UserManagerListItem,
    UserManagerRead,
)
from app.services.cache import invalidate_tags, user_tag


class NotFoundError(ValueError):
    """Клиент (или связанная сущность) не найден → 404."""


class ConflictError(ValueError):
    """Конфликт состояния (дубликат email, отсутствие курса НБ РБ) → 409."""


async def load_fixed_rate(db: AsyncSession, user: User) -> ExchangeRate | None:
    """User не имеет relationship на ExchangeRate — грузим явно."""
    if user.fixed_rate_id is None:
        return None
    return await db.get(ExchangeRate, user.fixed_rate_id)


class ManagerUsersService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------ helpers
    async def _get_client(self, user_id: uuid.UUID) -> User:
        user = await users_repo.get_client(self.db, user_id)
        if user is None:
            raise NotFoundError("Клиент не найден")
        return user

    # ------------------------------------------------------------- create
    async def create_client(self, manager: User, payload: ClientCreateIn) -> tuple[User, str]:
        email = payload.email.lower()
        if await users_repo.email_exists(self.db, email):
            raise ConflictError("Пользователь с таким email уже существует")

        temp_password = secrets.token_urlsafe(12)
        user = await users_repo.create_user(
            self.db,
            email=email,
            password_hash=hash_password(temp_password),
            full_name=payload.full_name,
            company=payload.company,
            phone=payload.phone,
        )
        if payload.discount_percent_all is not None:
            brand_ids = await users_repo.all_brand_ids(self.db)
            await users_repo.replace_discounts(
                self.db,
                user_id=user.id,
                items=[(brand_id, payload.discount_percent_all) for brand_id in brand_ids],
                manager_id=manager.id,
            )
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="user.create",
            target_type="user",
            target_id=user.id,
            after={
                "email": email,
                "full_name": payload.full_name,
                "company": payload.company,
                "phone": payload.phone,
                "discount_percent_all": (
                    str(payload.discount_percent_all)
                    if payload.discount_percent_all is not None
                    else None
                ),
            },
        )
        await notif_repo.create_notification(
            self.db,
            type="ACCOUNT_CREATED",
            user_id=user.id,
            channel=["inapp"],
            title="Аккаунт создан",
            body="Доступ к порталу создан. Временный пароль выдал менеджер.",
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user, temp_password

    # -------------------------------------------------------------- list
    async def list_users(
        self, q: str | None, page: int, per_page: int
    ) -> tuple[list[UserManagerListItem], int]:
        limit, offset = per_page, (page - 1) * per_page
        rows, total = await users_repo.fetch_users(self.db, q=q, limit=limit, offset=offset)
        items = [
            UserManagerListItem(
                id=row.User.id,
                email=row.User.email,
                full_name=row.User.full_name,
                company=row.User.company,
                phone=row.User.phone,
                is_active=row.User.is_active,
                display_currency=row.User.display_currency,
                created_at=row.User.created_at,
                fixed_rate_currency=row.fixed_rate_currency,
                avg_discount_percent=row.avg_discount_percent,
                orders_count=int(row.orders_count),
            )
            for row in rows
        ]
        return items, total

    # ------------------------------------------------------------ detail
    async def get_detail(self, user_id: uuid.UUID) -> tuple[User, list[DiscountOut]]:
        user = await self._get_client(user_id)
        return user, await self._discounts(user.id)

    async def _discounts(self, user_id: uuid.UUID) -> list[DiscountOut]:
        rows = await users_repo.fetch_discount_rows(self.db, user_id=user_id)
        return [
            DiscountOut(brand_id=row.brand_id, brand_name=row.brand_name, percent=row.percent)
            for row in rows
        ]

    # ------------------------------------------------------------ update
    async def update_client(
        self, manager: User, user_id: uuid.UUID, payload: UserPatchIn
    ) -> User:
        user = await self._get_client(user_id)
        data = payload.model_dump(exclude_unset=True)
        before: dict = {}
        after: dict = {}
        for field in ("full_name", "company", "phone", "display_currency"):
            value = data.get(field)
            if value is None:
                continue
            if getattr(user, field) != value:
                before[field] = getattr(user, field)
                after[field] = value
                setattr(user, field, value)
        if data.get("is_active") is not None and user.is_active != data["is_active"]:
            before["is_active"] = user.is_active
            after["is_active"] = data["is_active"]
            user.is_active = data["is_active"]

        if after:
            await audit_repo.create_audit(
                self.db,
                actor_id=manager.id,
                action="user.update",
                target_type="user",
                target_id=user.id,
                before=before,
                after=after,
            )
            await self.db.commit()
            await self.db.refresh(user)
            if "display_currency" in after:
                await invalidate_tags(user_tag(user.id))
        return user

    # ----------------------------------------------------- reset password
    async def reset_password(self, manager: User, user_id: uuid.UUID) -> tuple[User, str]:
        user = await self._get_client(user_id)
        temp_password = secrets.token_urlsafe(12)
        user.password_hash = hash_password(temp_password)
        revoked = await users_repo.revoke_sessions(self.db, user_id=user.id)
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="user.reset_password",
            target_type="user",
            target_id=user.id,
            after={"sessions_revoked": revoked},
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user, temp_password

    # ---------------------------------------------------------- discounts
    async def set_discounts(
        self, manager: User, user_id: uuid.UUID, payload: DiscountsIn
    ) -> list[DiscountOut]:
        user = await self._get_client(user_id)
        before = await users_repo.current_discount_map(self.db, user_id=user.id)
        await users_repo.replace_discounts(
            self.db,
            user_id=user.id,
            items=[(d.brand_id, d.percent) for d in payload.discounts],
            manager_id=manager.id,
        )
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="user.discount.update",
            target_type="user",
            target_id=user.id,
            before=before,
            after={str(d.brand_id): str(d.percent) for d in payload.discounts},
        )
        await self.db.commit()
        await invalidate_tags(user_tag(user.id))
        return await self._discounts(user.id)

    # --------------------------------------------------------- fixed rate
    async def set_fixed_rate(
        self, manager: User, user_id: uuid.UUID, payload: FixedRateIn
    ) -> User:
        user = await self._get_client(user_id)

        if payload.reset:
            before = None
            fixed = await load_fixed_rate(self.db, user)
            if fixed is not None:
                before = {
                    "currency_code": fixed.currency_code,
                    "rate": str(fixed.rate),
                    "source": fixed.source,
                }
            user.fixed_rate_id = None
            await audit_repo.create_audit(
                self.db,
                actor_id=manager.id,
                action="user.fixed_rate.reset",
                target_type="user",
                target_id=user.id,
                before=before,
            )
        else:
            if payload.currency_code is None:
                raise ValueError("Укажите currency_code или reset=true")
            if payload.rate is not None:
                rate_row = await rates_repo.upsert_manual(
                    self.db,
                    currency_code=payload.currency_code,
                    rate=payload.rate,
                    fetched_at=date.today(),
                )
            else:
                nbrb = await rates_repo.latest_nbrb(self.db, payload.currency_code)
                if nbrb is None:
                    raise ConflictError(
                        f"Курс НБ РБ для {payload.currency_code} не найден"
                    )
                rate_row = await rates_repo.upsert_manual(
                    self.db,
                    currency_code=payload.currency_code,
                    rate=nbrb.rate,
                    fetched_at=date.today(),
                    scale=nbrb.scale or 1,
                )
            user.fixed_rate_id = rate_row.id
            await audit_repo.create_audit(
                self.db,
                actor_id=manager.id,
                action="user.fixed_rate.set",
                target_type="user",
                target_id=user.id,
                after={
                    "currency_code": rate_row.currency_code,
                    "rate": str(rate_row.rate),
                    "source": rate_row.source,
                },
            )

        await self.db.commit()
        await self.db.refresh(user)
        await invalidate_tags(user_tag(user.id))
        return user

    # ------------------------------------------------------ schema helper
    async def to_read(self, user: User) -> UserManagerRead:
        fixed = await load_fixed_rate(self.db, user)
        return UserManagerRead.from_user(user, RateOut.model_validate(fixed) if fixed else None)
