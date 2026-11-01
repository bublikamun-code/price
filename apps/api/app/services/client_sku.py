"""Кросс-справочник клиентских артикулов: CRUD и apply-csv (§16 п.43).

Справочник — свойство организации: клиентская ветка резолвит активную
организацию через ``OrganizationContextService`` (соло-клиент без орги — 422
``ORGANIZATION_REQUIRED``), staff-ветка manager-роутера берет организацию из
пути и проверяет только роль (MANAGER/ADMIN). Мутации в клиентской ветке —
OWNER/BUYER (как адресная книга), чтение — все участники.

``apply_csv`` парсит вставку теми же формами строк, что и фронтовой
bulk-add.vue (`sku`, `sku=qty`, `sku;qty`, `sku⇥qty`, `#`-комментарии,
дефолт qty=1), мапит артикулы через справочник, батчем считает клиентские
цены и немедленно наполняет корзину v2 тем же сервисом, что и ручное
добавление (повтор = инкремент qty, ARCHIVED-товар отклоняется).
"""
from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.client_sku import ClientSkuMapping
from app.models.enums import OrganizationRole, StockStatus, UserRole
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import cart as cart_repo
from app.repositories import catalog as catalog_repo
from app.repositories import client_sku as client_sku_repo
from app.repositories import organizations as organizations_repo
from app.schemas.v2.client_sku import (
    ClientSkuApplyOut,
    ClientSkuApplyRow,
    ClientSkuApplySummary,
)
from app.schemas.v2.common import Money
from app.services.cart_v2 import CartV2Error, CartV2Service
from app.services.organizations import OrganizationContextService
from app.services.pricing import PricingService

# Тот же лимит позиций, что у bulk-add (schemas/catalog.py BULK_ITEMS_MAX).
CSV_MAX_ROWS = 500

# Семантика парсера bulk-add.vue: ^(\S+?)(?:[=\t;]\s*(\d+))?$ — ленивый
# префикс без пробелов, затем опционально «=qty», «;qty» или «⇥qty».
_LINE_RE = re.compile(r"^(\S+?)(?:[=\t;]\s*(\d+))?$")


class ClientSkuMappingError(Exception):
    """Доменная ошибка справочника; роутер мапит её в Problem Details."""

    def __init__(self, code: str, status_code: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.title = title
        self.detail = detail


class MappingNotFoundError(ClientSkuMappingError):
    code = "CLIENT_SKU_MAPPING_NOT_FOUND"
    status_code = 404
    title = "Связка не найдена"

    def __init__(self, detail: str = "Связка не найдена в этой организации") -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class MappingExistsError(ClientSkuMappingError):
    code = "CLIENT_SKU_MAPPING_EXISTS"
    status_code = 409
    title = "Связка уже существует"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class ClientSkuForbiddenError(ClientSkuMappingError):
    code = "PERMISSION_DENIED"
    status_code = 403
    title = "Недостаточно прав"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class OrganizationRequiredError(ClientSkuMappingError):
    code = "ORGANIZATION_REQUIRED"
    status_code = 422
    title = "Нет организации"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class OrganizationMissingError(ClientSkuMappingError):
    code = "ORGANIZATION_NOT_FOUND"
    status_code = 404
    title = "Организация не найдена"

    def __init__(self, detail: str = "Организация не найдена") -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class ProductNotFoundError(ClientSkuMappingError):
    code = "PRODUCT_NOT_FOUND"
    status_code = 404
    title = "Товар не найден"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class ProductArchivedError(ClientSkuMappingError):
    code = "PRODUCT_ARCHIVED"
    status_code = 422
    title = "Товар в архиве"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class StaleMappingVersionError(ClientSkuMappingError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Связка уже изменена"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


class InvalidCsvError(ClientSkuMappingError):
    code = "VALIDATION_ERROR"
    status_code = 422
    title = "Ошибка валидации"

    def __init__(self, detail: str) -> None:
        super().__init__(self.code, self.status_code, self.title, detail)


@dataclass(frozen=True)
class _Line:
    """Одна непустая строка CSV после парсера."""

    raw_sku: str
    qty: int
    error: str | None  # не-None — строка в отчёт UNKNOWN, файл не валим


def _parse_lines(csv_text: str) -> list[_Line]:
    lines: list[_Line] = []
    for raw in csv_text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            # Пустые строки и #-комментарии пропускаются (§16 п.43 п.5).
            continue
        match = _LINE_RE.match(line)
        if match is None:
            lines.append(_Line(raw_sku=line, qty=0, error="Строка не распознана"))
            continue
        qty = int(match.group(2)) if match.group(2) else 1
        if qty < 1:
            lines.append(
                _Line(raw_sku=match.group(1), qty=qty, error="Некорректное количество")
            )
            continue
        lines.append(_Line(raw_sku=match.group(1), qty=qty, error=None))
    return lines


class ClientSkuService:
    """CRUD справочника + применение CSV-вставки к корзине v2."""

    _WRITER_ROLES = {OrganizationRole.OWNER, OrganizationRole.BUYER}
    _STAFF_ROLES = {UserRole.MANAGER, UserRole.ADMIN}

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ---------- scope / права -------------------------------------------------

    async def _resolve_scope(self, user: User) -> tuple[uuid.UUID, str] | None:
        """(organization_id, role) активной организации; None у соло-клиента."""
        context = await OrganizationContextService(self.db).resolve(user)
        if context.organization_id is None:
            return None
        role = next(
            (
                membership.role
                for membership in context.memberships
                if membership.organization_id == context.organization_id
            ),
            None,
        )
        return context.organization_id, role or OrganizationRole.VIEWER.value

    async def _resolve_target(
        self,
        user: User,
        *,
        organization_id: uuid.UUID | None,
        writer_required: bool,
    ) -> uuid.UUID:
        """Организация для операции: staff-путь (org из пути) или активная орга."""
        if organization_id is not None:
            # Manager-роутер: организация из пути, membership-проверок нет.
            if user.role not in self._STAFF_ROLES:
                raise ClientSkuForbiddenError(
                    "Вести справочник организации может только менеджер"
                )
            if await organizations_repo.get_organization(
                self.db, organization_id=organization_id
            ) is None:
                raise OrganizationMissingError()
            return organization_id

        scope = await self._resolve_scope(user)
        if scope is None:
            raise OrganizationRequiredError(
                "Справочник клиентских артикулов доступен только членам организации"
            )
        organization_uuid, role = scope
        if writer_required:
            self._require_writer(role)
        return organization_uuid

    @staticmethod
    def _require_writer(role: str) -> None:
        if role not in {item.value for item in ClientSkuService._WRITER_ROLES}:
            raise ClientSkuForbiddenError(
                "Управлять справочником артикулов могут только OWNER и BUYER"
            )

    # ---------- общие проверки ------------------------------------------------

    @staticmethod
    def _audit_state(mapping: ClientSkuMapping) -> dict:
        return {
            "id": str(mapping.id),
            "organizationId": str(mapping.organization_id),
            "clientSku": mapping.client_sku,
            "productId": str(mapping.product_id),
            "note": mapping.note,
            "version": mapping.version,
        }

    async def _ensure_product_usable(self, product_id: uuid.UUID) -> Product:
        product = await catalog_repo.get_product_by_id(self.db, product_id)
        if product is None or product.deleted_at is not None:
            raise ProductNotFoundError(f"Товар {product_id} не найден")
        if product.stock_status == StockStatus.ARCHIVED:
            raise ProductArchivedError(
                f"Товар {product.sku} в архиве — выберите действующий артикул"
            )
        return product

    # ---------- CRUD ----------------------------------------------------------

    async def list_page(
        self,
        user: User,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
        organization_id: uuid.UUID | None = None,
    ) -> tuple[list[ClientSkuMapping], int]:
        organization_uuid = await self._resolve_target(
            user, organization_id=organization_id, writer_required=False
        )
        offset = (page - 1) * page_size
        rows = await client_sku_repo.list_page(
            self.db,
            organization_id=organization_uuid,
            query=query,
            offset=offset,
            limit=page_size,
        )
        total = await client_sku_repo.count(
            self.db, organization_id=organization_uuid, query=query
        )
        return rows, total

    async def create(
        self,
        user: User,
        *,
        client_sku: str,
        product_id: uuid.UUID,
        note: str | None,
        organization_id: uuid.UUID | None = None,
    ) -> ClientSkuMapping:
        organization_uuid = await self._resolve_target(
            user, organization_id=organization_id, writer_required=True
        )
        sku = client_sku.strip()
        await self._ensure_product_usable(product_id)
        if (
            await client_sku_repo.get_by_sku(
                self.db, organization_id=organization_uuid, client_sku=sku
            )
            is not None
        ):
            raise MappingExistsError(
                f"Связка для артикула «{sku}» уже существует в организации"
            )
        try:
            # savepoint: IntegrityError по uq(org, client_sku) (гонка) не должен
            # откатывать внешнюю транзакцию роутера (паттерн §16 п.40/41).
            async with self.db.begin_nested():
                mapping = await client_sku_repo.create(
                    self.db,
                    organization_id=organization_uuid,
                    client_sku=sku,
                    product_id=product_id,
                    note=note,
                )
        except IntegrityError as exc:
            raise MappingExistsError(
                f"Связка для артикула «{sku}» уже существует в организации"
            ) from exc
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="client_sku_mapping.create",
            target_type="client_sku_mapping",
            target_id=mapping.id,
            after=self._audit_state(mapping),
        )
        return mapping

    async def update(
        self,
        user: User,
        *,
        mapping_id: uuid.UUID,
        expected_version: int,
        changes: dict[str, object],
        organization_id: uuid.UUID | None = None,
    ) -> ClientSkuMapping:
        organization_uuid = await self._resolve_target(
            user, organization_id=organization_id, writer_required=True
        )
        mapping = await client_sku_repo.get(
            self.db, organization_id=organization_uuid, mapping_id=mapping_id
        )
        if mapping is None:
            raise MappingNotFoundError()
        if mapping.version != expected_version:
            raise StaleMappingVersionError(
                f"Ожидалась версия {expected_version}, актуальная версия {mapping.version}"
            )
        product_id = changes.get("product_id")
        if "product_id" in changes:
            if product_id is None:  # defensive: роутер отсекает null
                raise ClientSkuMappingError(
                    "VALIDATION_ERROR",
                    422,
                    "Ошибка валидации",
                    "Поле productId обязательно и не может быть null",
                )
            await self._ensure_product_usable(uuid.UUID(str(product_id)))
        before = self._audit_state(mapping)
        mapping = await client_sku_repo.update(
            self.db, mapping=mapping, changes=changes
        )
        # После UPDATE атрибут updated_at истекает (onupdate=func.now() —
        # значение вычисляет БД); refresh до доступа в роутере (паттерн
        # volume_tiers, иначе async-перечитка подняла бы MissingGreenlet).
        await self.db.refresh(mapping)
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="client_sku_mapping.update",
            target_type="client_sku_mapping",
            target_id=mapping.id,
            before=before,
            after=self._audit_state(mapping),
        )
        return mapping

    async def delete(
        self,
        user: User,
        *,
        mapping_id: uuid.UUID,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        organization_uuid = await self._resolve_target(
            user, organization_id=organization_id, writer_required=True
        )
        mapping = await client_sku_repo.get(
            self.db, organization_id=organization_uuid, mapping_id=mapping_id
        )
        if mapping is None:
            raise MappingNotFoundError()
        before = self._audit_state(mapping)
        await client_sku_repo.delete(self.db, mapping=mapping)
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="client_sku_mapping.delete",
            target_type="client_sku_mapping",
            target_id=mapping_id,
            before=before,
        )

    # ---------- apply-csv -----------------------------------------------------

    async def apply_csv(self, user: User, *, csv_text: str) -> ClientSkuApplyOut:
        """Отчёт matched/unknown/ambiguous + наполнение корзины v2.

        Частичный успех: некорректные/неизвестные строки помечаются и не мешают
        остальным. Matched добавляется в корзину тем же сервисом, что и ручное
        добавление (повтор = инкремент qty, ARCHIVED отклоняется).
        """
        scope = await self._resolve_scope(user)
        if scope is None:
            raise OrganizationRequiredError(
                "Применение списка доступно только членам организации"
            )
        organization_id, _role = scope

        lines = _parse_lines(csv_text)
        valid = [line for line in lines if line.error is None]
        if not lines:
            raise InvalidCsvError("Список пуст — добавьте хотя бы одну позицию")
        if len(valid) > CSV_MAX_ROWS:
            raise InvalidCsvError(
                f"Слишком много позиций ({len(valid)}): максимум {CSV_MAX_ROWS}"
            )

        # Дубль артикула в файле (регистр не важен — как CITEXT) → все
        # вхождения AMBIGUOUS, qty молча не суммируется (§16 п.43 п.3).
        occurrences = Counter(line.raw_sku.lower() for line in valid)
        duplicates = {sku for sku, count in occurrences.items() if count > 1}
        mappings = await client_sku_repo.get_by_skus(
            self.db,
            organization_id=organization_id,
            client_skus=[line.raw_sku for line in valid],
        )

        # Товары под matched-маппинги — одним запросом (без удалённых).
        mapping_list = [
            mappings[line.raw_sku.lower()]
            for line in valid
            if line.error is None
            and line.raw_sku.lower() not in duplicates
            and line.raw_sku.lower() in mappings
        ]
        product_ids = list({mapping.product_id for mapping in mapping_list})
        products = await client_sku_repo.get_products_by_ids(self.db, product_ids)

        # Клиентские цены — батчем, как в resolve-bulk (без объёмных ступеней:
        # количество строки знает только корзина после инкремента).
        alive = [
            product
            for product in products.values()
            if product.stock_status != StockStatus.ARCHIVED
        ]
        prices: dict[uuid.UUID, dict] = {}
        if alive:
            prices = await PricingService(self.db).price_products(
                alive, user, "fixed", organization_id=organization_id
            )

        rows: list[ClientSkuApplyRow] = []
        summary = ClientSkuApplySummary()
        cart_service = CartV2Service(self.db)
        expected_version: int | None = None
        cart_version: str | None = None

        for line in lines:
            if line.error is not None:
                summary.unknown += 1
                rows.append(
                    ClientSkuApplyRow(
                        client_sku=line.raw_sku,
                        qty=line.qty,
                        status="UNKNOWN",
                        message=line.error,
                    )
                )
                continue
            key = line.raw_sku.lower()
            if key in duplicates:
                summary.ambiguous += 1
                rows.append(
                    ClientSkuApplyRow(
                        client_sku=line.raw_sku,
                        qty=line.qty,
                        status="AMBIGUOUS",
                        message="Артикул встречается в файле более одного раза",
                    )
                )
                continue
            mapping = mappings.get(key)
            if mapping is None:
                summary.unknown += 1
                rows.append(
                    ClientSkuApplyRow(
                        client_sku=line.raw_sku,
                        qty=line.qty,
                        status="UNKNOWN",
                        message="Не найден в справочнике",
                    )
                )
                continue
            product = products.get(mapping.product_id)
            if product is None or product.stock_status == StockStatus.ARCHIVED:
                # Маппинг сохраняется — клиент перемапит (§16 п.43 п.4).
                summary.unknown += 1
                rows.append(
                    ClientSkuApplyRow(
                        client_sku=line.raw_sku,
                        qty=line.qty,
                        status="UNKNOWN",
                        message="Товар в архиве",
                    )
                )
                continue
            if expected_version is None:
                # Блокируем строку корзины до конца apply — конкурентная
                # мутация корзины подождёт (версии внутри apply цепочкой).
                await cart_repo.get_or_create_cart(
                    self.db, user_id=user.id, organization_id=organization_id
                )
                locked = await cart_repo.get_cart_for_update(
                    self.db,
                    user_id=user.id,
                    organization_id=organization_id,
                )
                if locked is None:
                    raise RuntimeError("scoped cart disappeared during apply-csv")
                expected_version = locked.version
            try:
                cart = await cart_service.add(
                    user,
                    organization_id=organization_id,
                    expected_version=expected_version,
                    product_id=product.id,
                    quantity=str(line.qty),
                    note=None,
                )
            except CartV2Error as exc:  # не должно падать: товар уже проверен
                summary.unknown += 1
                rows.append(
                    ClientSkuApplyRow(
                        client_sku=line.raw_sku,
                        qty=line.qty,
                        status="UNKNOWN",
                        message=exc.detail,
                    )
                )
                continue
            expected_version = cart.version
            cart_version = str(cart.version)
            summary.matched += 1
            summary.cart_added += 1
            price = prices.get(product.id)
            rows.append(
                ClientSkuApplyRow(
                    client_sku=line.raw_sku,
                    qty=line.qty,
                    status="MATCHED",
                    product_id=product.id,
                    product_name=product.name,
                    product_sku=product.sku,
                    unit_price=(
                        None if price is None else _row_money(price)
                    ),
                    stock_status=_stock_status_value(product),
                )
            )

        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="client_sku_mapping.apply_csv",
            target_type="organization",
            target_id=organization_id,
            after={
                "matched": summary.matched,
                "unknown": summary.unknown,
                "ambiguous": summary.ambiguous,
                "cartAdded": summary.cart_added,
            },
        )
        return ClientSkuApplyOut(
            rows=rows, summary=summary, cart_version=cart_version
        )


def _stock_status_value(product: Product) -> str:
    return (
        product.stock_status.value
        if hasattr(product.stock_status, "value")
        else str(product.stock_status)
    )


def _row_money(price: dict) -> Money:
    """Клиентская цена строки отчёта — каноническая Money-строка (§6)."""
    return Money.from_value(
        Decimal(str(price["client_price"])), currency=price["currency"]
    )


__all__ = [
    "ClientSkuForbiddenError",
    "ClientSkuMappingError",
    "ClientSkuService",
    "InvalidCsvError",
    "MappingExistsError",
    "MappingNotFoundError",
    "OrganizationMissingError",
    "OrganizationRequiredError",
    "ProductArchivedError",
    "ProductNotFoundError",
    "StaleMappingVersionError",
]
