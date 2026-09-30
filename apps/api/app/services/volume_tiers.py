"""Лестницы скидок за объём: use-cases менеджера над ``brand_volume_tiers``.

См. ARCHITECTURE_PLAN.md §6 «Скидки за объём», §8, §16 п.41.

Ступень — самостоятельный ресурс с собственной ``version``: правка порога
менеджером не должна затирать чужую правку процента, поэтому ``If-Match``
сверяет версию **ступени**, а не бренда (по аналогии с решением по счёту,
§16 п.40 п.8). Валидация диапазонов — на сервере, потому что на клиенте она
всегда обходится прямым вызовом API.

Коммитит вызывающий (роутер), сервис только flush — паттерн §4.
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Brand, BrandVolumeTier
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import volume_tiers as tiers_repo
from app.services.cache import VOLUME_TIERS_TAG, invalidate_tags

MIN_MIN_QTY = 1
MIN_DISCOUNT = Decimal("0")
MAX_DISCOUNT = Decimal("100")


class VolumeTierError(Exception):
    code = "VOLUME_TIER_ERROR"
    status_code = 400
    title = "Ошибка скидки за объём"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class VolumeTierNotFoundError(VolumeTierError):
    code = "VOLUME_TIER_NOT_FOUND"
    status_code = 404
    title = "Ступень скидки не найдена"


class VolumeTierDuplicateThresholdError(VolumeTierError):
    code = "VOLUME_TIER_DUPLICATE_THRESHOLD"
    status_code = 409
    title = "Такой порог уже есть"


class StaleVolumeTierVersionError(VolumeTierError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Ступень уже изменена"


class InvalidVolumeTierError(VolumeTierError):
    code = "VALIDATION_ERROR"
    status_code = 422
    title = "Ошибка валидации"


def _validate(min_qty: int, discount_percent) -> None:
    """Домены значений из §5.2: ``min_qty >= 1``, ``0 < discount_percent < 100``.

    Ноль процентов — ступень без эффекта, а 100% — отдача товара без оплаты;
    оба значения в таблице не хранятся.
    """
    if min_qty < MIN_MIN_QTY:
        raise InvalidVolumeTierError("Порог должен быть не меньше 1 штуки")
    try:
        percent = Decimal(str(discount_percent))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidVolumeTierError("Процент скидки должен быть числом") from exc
    if not (MIN_DISCOUNT < percent < MAX_DISCOUNT):
        raise InvalidVolumeTierError("Процент скидки должен быть строго между 0 и 100")


class VolumeTierService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _audit_state(tier: BrandVolumeTier) -> dict:
        return {
            "id": str(tier.id),
            "brandId": str(tier.brand_id),
            "minQty": tier.min_qty,
            "discountPercent": str(tier.discount_percent),
            "version": tier.version,
        }

    async def list_for_brand(self, *, brand_id: uuid.UUID) -> list[BrandVolumeTier]:
        brand = await self.db.get(Brand, brand_id)
        if brand is None:
            raise VolumeTierNotFoundError("Бренд не найден")
        return await tiers_repo.fetch_tiers(self.db, brand_id)

    async def create(
        self,
        *,
        brand_id: uuid.UUID,
        min_qty: int,
        discount_percent,
        actor: User,
    ) -> BrandVolumeTier:
        _validate(min_qty, discount_percent)
        if await self.db.get(Brand, brand_id) is None:
            raise VolumeTierNotFoundError("Бренд не найден")
        if (
            await tiers_repo.find_tier_by_threshold(
                self.db, brand_id=brand_id, min_qty=min_qty
            )
            is not None
        ):
            raise VolumeTierDuplicateThresholdError(
                f"Порог от {min_qty} шт для этого бренда уже занят"
            )
        tier = BrandVolumeTier(
            brand_id=brand_id,
            min_qty=min_qty,
            discount_percent=Decimal(str(discount_percent)),
        )
        self.db.add(tier)
        try:
            # savepoint: IntegrityError по uq(brand_id, min_qty) не должен
            # откатывать внешнюю транзакцию роутера (паттерн §16 п.40).
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as exc:
            raise VolumeTierDuplicateThresholdError(
                f"Порог от {min_qty} шт для этого бренда уже занят"
            ) from exc
        await audit_repo.create_audit(
            self.db,
            actor_id=actor.id,
            action="volume_tier.create",
            target_type="brand_volume_tier",
            target_id=tier.id,
            after=self._audit_state(tier),
        )
        # Ступень — самостоятельный ресурс: её версия растёт при правке порога
        # или процента, а brands.version при этом не трогается.
        await self.db.flush()
        await invalidate_tags(VOLUME_TIERS_TAG, f"brand:{brand_id}")
        return tier

    async def update(
        self,
        *,
        tier_id: uuid.UUID,
        expected_version: int,
        min_qty: int | None,
        discount_percent,
        actor: User,
    ) -> BrandVolumeTier:
        tier = await tiers_repo.get_tier(self.db, tier_id)
        if tier is None:
            raise VolumeTierNotFoundError("Ступень не найдена")
        if tier.version != expected_version:
            raise StaleVolumeTierVersionError(
                "Ступень уже изменена — обновите список и повторите"
            )
        before = self._audit_state(tier)
        new_min_qty = tier.min_qty if min_qty is None else min_qty
        new_percent = (
            tier.discount_percent if discount_percent is None else discount_percent
        )
        _validate(new_min_qty, new_percent)

        if new_min_qty != tier.min_qty:
            clash = await tiers_repo.find_tier_by_threshold(
                self.db, brand_id=tier.brand_id, min_qty=new_min_qty
            )
            if clash is not None and clash.id != tier.id:
                raise VolumeTierDuplicateThresholdError(
                    f"Порог от {new_min_qty} шт для этого бренда уже занят"
                )
        tier.min_qty = new_min_qty
        tier.discount_percent = Decimal(str(new_percent))
        tier.version += 1
        try:
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as exc:
            raise VolumeTierDuplicateThresholdError(
                f"Порог от {new_min_qty} шт для этого бренда уже занят"
            ) from exc
        # После UPDATE атрибут updated_at истекает (onupdate=func.now() —
        # значение вычисляет БД), и ленивая перечитка в async-контексте
        # подняла бы MissingGreenlet. Refresh делает её заранее.
        await self.db.refresh(tier)
        await audit_repo.create_audit(
            self.db,
            actor_id=actor.id,
            action="volume_tier.update",
            target_type="brand_volume_tier",
            target_id=tier.id,
            before=before,
            after=self._audit_state(tier),
        )
        await invalidate_tags(VOLUME_TIERS_TAG, f"brand:{tier.brand_id}")
        return tier

    async def delete(
        self, *, tier_id: uuid.UUID, expected_version: int, actor: User
    ) -> None:
        tier = await tiers_repo.get_tier(self.db, tier_id)
        if tier is None:
            raise VolumeTierNotFoundError("Ступень не найдена")
        if tier.version != expected_version:
            raise StaleVolumeTierVersionError(
                "Ступень уже изменена — обновите список и повторите"
            )
        brand_id = tier.brand_id
        before = self._audit_state(tier)
        await self.db.delete(tier)
        await audit_repo.create_audit(
            self.db,
            actor_id=actor.id,
            action="volume_tier.delete",
            target_type="brand_volume_tier",
            target_id=tier_id,
            before=before,
        )
        await invalidate_tags(VOLUME_TIERS_TAG, f"brand:{brand_id}")


__all__ = [
    "InvalidVolumeTierError",
    "StaleVolumeTierVersionError",
    "VolumeTierDuplicateThresholdError",
    "VolumeTierError",
    "VolumeTierNotFoundError",
    "VolumeTierService",
]
