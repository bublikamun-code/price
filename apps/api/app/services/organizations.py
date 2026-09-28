"""Organization context resolution.

A selected organization is usable only when the user has an explicit active
membership.  The resolver never derives ownership from ``User.company``.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrganizationRole, UserRole
from app.models.organization import OrganizationAddress, OrganizationMembership
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import organizations as organizations_repo


@dataclass(frozen=True)
class OrganizationMembershipContext:
    organization_id: uuid.UUID
    legal_name: str
    display_name: str | None
    role: str
    status: str
    is_primary: bool


@dataclass(frozen=True)
class OrganizationContext:
    organization_id: uuid.UUID | None
    memberships: tuple[OrganizationMembershipContext, ...]

    @property
    def is_organization_scope(self) -> bool:
        return self.organization_id is not None


class OrganizationContextService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve(self, user: User) -> OrganizationContext:
        records = await organizations_repo.fetch_memberships(self.db, user_id=user.id)
        memberships = tuple(
            OrganizationMembershipContext(
                organization_id=record.organization.id,
                legal_name=record.organization.legal_name,
                display_name=record.organization.display_name,
                role=record.membership.role.value,
                status=("ACTIVE" if record.membership.is_active else "SUSPENDED"),
                is_primary=record.membership.is_primary,
            )
            for record in records
        )
        active_ids = {
            record.organization.id
            for record in records
            if record.membership.is_active and record.organization.is_active
        }
        selected = user.active_organization_id
        if selected not in active_ids:
            selected = None
        return OrganizationContext(
            organization_id=selected,
            memberships=memberships,
        )

    async def can_access(self, user: User, organization_id: uuid.UUID) -> bool:
        return await organizations_repo.has_active_membership(
            self.db, user_id=user.id, organization_id=organization_id
        )


class OrganizationManagementError(Exception):
    """Transport-neutral organization control-plane error."""

    code = "ORGANIZATION_ERROR"
    status_code = 400
    title = "Ошибка организации"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class OrganizationNotFoundError(OrganizationManagementError):
    code = "ORGANIZATION_NOT_FOUND"
    status_code = 404
    title = "Организация не найдена"


class MembershipNotFoundError(OrganizationManagementError):
    code = "MEMBERSHIP_NOT_FOUND"
    status_code = 404
    title = "Участник организации не найден"


class MembershipTargetNotFoundError(OrganizationManagementError):
    code = "MEMBERSHIP_TARGET_NOT_FOUND"
    status_code = 404
    title = "Пользователь для участника не найден"


class MembershipConflictError(OrganizationManagementError):
    code = "MEMBERSHIP_ALREADY_EXISTS"
    status_code = 409
    title = "Пользователь уже является участником"


class InvalidMembershipTargetError(OrganizationManagementError):
    code = "MEMBERSHIP_TARGET_INVALID"
    status_code = 400
    title = "Недопустимый участник организации"


class LastOwnerProtectionError(OrganizationManagementError):
    code = "LAST_OWNER_PROTECTED"
    status_code = 409
    title = "Последнего владельца нельзя изменить"


class StaleMembershipVersionError(OrganizationManagementError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Ресурс изменился"


class InvalidOrganizationSelectionError(OrganizationManagementError):
    code = "ORGANIZATION_SELECTION_INVALID"
    status_code = 400
    title = "Недопустимая организация"


class OrganizationManagementService:
    """Manager/admin organization operations over explicit memberships."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _membership_audit_state(
        membership: OrganizationMembership,
    ) -> dict[str, str | bool | int]:
        return {
            "organizationId": str(membership.organization_id),
            "role": getattr(membership.role, "value", membership.role),
            "isActive": membership.is_active,
            "isPrimary": membership.is_primary,
            "version": membership.version,
        }

    @staticmethod
    def _ensure_staff(actor: User) -> None:
        if actor.role not in {UserRole.MANAGER, UserRole.ADMIN}:
            raise OrganizationManagementError(
                "Управление организациями доступно только manager/admin"
            )

    async def list_organizations(self, actor: User):
        self._ensure_staff(actor)
        return await organizations_repo.list_organizations(self.db)

    async def list_organizations_page(
        self,
        actor: User,
        *,
        query: str | None,
        sort: str,
        limit: int,
        after: dict[str, str] | None,
    ):
        self._ensure_staff(actor)
        return await organizations_repo.fetch_organizations_page(
            self.db, q=query, sort=sort, limit=limit, after=after
        )

    async def get_organization(self, actor: User, *, organization_id: uuid.UUID):
        self._ensure_staff(actor)
        organization = await organizations_repo.get_organization(
            self.db, organization_id=organization_id
        )
        if organization is None:
            raise OrganizationNotFoundError("Организация не найдена")
        return organization

    async def list_members(self, actor: User, *, organization_id: uuid.UUID):
        self._ensure_staff(actor)
        await self.get_organization(actor, organization_id=organization_id)
        return await organizations_repo.list_members(
            self.db, organization_id=organization_id
        )

    async def list_members_page(
        self,
        actor: User,
        *,
        organization_id: uuid.UUID,
        query: str | None,
        sort: str,
        limit: int,
        after: dict[str, str] | None,
    ):
        self._ensure_staff(actor)
        await self.get_organization(actor, organization_id=organization_id)
        return await organizations_repo.fetch_members_page(
            self.db,
            organization_id=organization_id,
            q=query,
            sort=sort,
            limit=limit,
            after=after,
        )

    async def add_member(
        self,
        actor: User,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: OrganizationRole,
        is_active: bool,
        is_primary: bool,
    ):
        self._ensure_staff(actor)
        await self.get_organization(actor, organization_id=organization_id)
        target = await organizations_repo.get_user(self.db, user_id=user_id)
        if target is None:
            raise MembershipTargetNotFoundError("Пользователь для участника не найден")
        if target.role != UserRole.CLIENT:
            raise InvalidMembershipTargetError(
                "Commercial organization members must be existing CLIENT users"
            )
        existing = await organizations_repo.get_membership(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if existing is not None:
            raise MembershipConflictError("Пользователь уже является участником")
        try:
            async with self.db.begin_nested():
                membership = await organizations_repo.add_membership(
                    self.db,
                    organization_id=organization_id,
                    user_id=user_id,
                    role=role,
                    is_active=is_active,
                    is_primary=is_primary,
                )
                await audit_repo.create_audit(
                    self.db,
                    actor_id=actor.id,
                    action="organization.membership.add",
                    target_type="organization_membership",
                    target_id=user_id,
                    after=self._membership_audit_state(membership),
                )
                return membership
        except IntegrityError as exc:
            raise MembershipConflictError("Пользователь уже является участником") from exc

    async def update_member(
        self,
        actor: User,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        expected_version: int,
        role: OrganizationRole | None,
        is_active: bool | None,
        is_primary: bool | None,
        body_version: int | None = None,
    ):
        self._ensure_staff(actor)
        # Lock the organization row to serialize owner-count protection across
        # concurrent membership updates for the same organization.
        organization = await organizations_repo.get_organization(
            self.db, organization_id=organization_id, for_update=True
        )
        if organization is None:
            raise OrganizationNotFoundError("Организация не найдена")
        membership = await organizations_repo.get_membership(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            for_update=True,
        )
        if membership is None:
            raise MembershipNotFoundError("Участник организации не найден")
        if (
            expected_version != membership.version
            or (body_version is not None and body_version != expected_version)
        ):
            raise StaleMembershipVersionError(
                "Версия membership устарела; повторите чтение и обновление"
            )

        new_role = role if role is not None else membership.role
        new_is_active = is_active if is_active is not None else membership.is_active
        new_is_primary = is_primary if is_primary is not None else membership.is_primary
        loses_owner = (
            membership.role == OrganizationRole.OWNER
            and membership.is_active
            and (new_role != OrganizationRole.OWNER or not new_is_active)
        )
        if loses_owner and await organizations_repo.count_active_owners(
            self.db, organization_id=organization_id
        ) <= 1:
            raise LastOwnerProtectionError(
                "В организации должен остаться хотя бы один активный OWNER"
            )

        before = self._membership_audit_state(membership)
        updated = await organizations_repo.update_membership_atomic(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            expected_version=expected_version,
            role=new_role,
            is_active=new_is_active,
            is_primary=new_is_primary,
        )
        if not updated:
            raise StaleMembershipVersionError(
                "Версия membership устарела; повторите чтение и обновление"
            )
        await self.db.refresh(membership)
        if not new_is_active:
            await organizations_repo.clear_active_organization_for_user(
                self.db, user_id=user_id, organization_id=organization_id
            )
        await audit_repo.create_audit(
            self.db,
            actor_id=actor.id,
            action="organization.membership.update",
            target_type="organization_membership",
            target_id=user_id,
            before=before,
            after=self._membership_audit_state(membership),
        )
        return membership

    async def select_organization(
        self, user: User, *, organization_id: uuid.UUID | None
    ) -> OrganizationContext:
        if organization_id is not None and not await organizations_repo.has_active_membership(
            self.db, user_id=user.id, organization_id=organization_id
        ):
            raise InvalidOrganizationSelectionError(
                "Можно выбрать только организацию с активным membership"
            )
        user.active_organization_id = organization_id
        await self.db.flush()
        return await OrganizationContextService(self.db).resolve(user)


# --- Адресная книга доставки (Этап 2 дорожной карты) ------------------------


class OrganizationAddressError(Exception):
    """Доменная ошибка адресной книги; роутер мапит её в Problem Details."""

    def __init__(
        self,
        code: str,
        status_code: int,
        title: str,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.title = title
        self.detail = detail


class OrganizationAddressService:
    """CRUD адресов организации от имени члена организации.

    Запись — OWNER/BUYER (CONTACT/VIEWER читают). Повторный POST с тем же
    (kind, address_line) возвращает существующий адрес — идемпотентность без
    отдельного key→result-хранилища: конвергентное поведение даёт сам
    уникальный ключ (org, kind, address_line) из миграции 0013.
    """

    _WRITER_ROLES = {OrganizationRole.OWNER, OrganizationRole.BUYER}

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _resolve_scope(self, user: User) -> tuple[uuid.UUID, str] | None:
        """(organization_id, role) активной организации; None у legacy-одиночки."""
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

    @staticmethod
    def _require_writer(role: str) -> None:
        if role not in {item.value for item in OrganizationAddressService._WRITER_ROLES}:
            raise OrganizationAddressError(
                code="ADDRESS_FORBIDDEN",
                status_code=403,
                title="Недостаточно прав",
                detail="Управлять адресами организации могут только OWNER и BUYER",
            )

    async def list_addresses(self, user: User) -> list[OrganizationAddress]:
        scope = await self._resolve_scope(user)
        if scope is None:
            return []
        return await organizations_repo.list_addresses(
            self.db, organization_id=scope[0]
        )

    async def create_address(
        self, user: User, *, kind: str, address_line: str, **fields
    ) -> OrganizationAddress:
        scope = await self._resolve_scope(user)
        if scope is None:
            raise OrganizationAddressError(
                code="NO_ORGANIZATION",
                status_code=409,
                title="Нет организации",
                detail="Адресная книга доступна только членам организации",
            )
        organization_id, role = scope
        self._require_writer(role)
        existing = await organizations_repo.find_same_address(
            self.db,
            organization_id=organization_id,
            kind=kind,
            address_line=address_line,
        )
        if existing is not None:
            return existing
        if fields.get("is_default"):
            await organizations_repo.clear_address_default(
                self.db, organization_id=organization_id, kind=kind
            )
        address = OrganizationAddress(
            organization_id=organization_id,
            kind=kind,
            address_line=address_line,
            **fields,
        )
        self.db.add(address)
        await self.db.commit()
        await self.db.refresh(address)
        return address

    async def update_address(
        self,
        user: User,
        *,
        address_id: uuid.UUID,
        changes: dict[str, object],
    ) -> OrganizationAddress:
        """Частичное обновление. `changes` содержит только явно переданные поля.

        Различение absent/null делает роутер (pydantic model_fields_set):
        null у nullable-колонок очищает значение, absent сохраняет прежнее.
        """
        scope = await self._resolve_scope(user)
        if scope is None:
            raise OrganizationAddressError(
                code="ADDRESS_NOT_FOUND",
                status_code=404,
                title="Адрес не найден",
                detail="Адрес не найден в текущей организации",
            )
        organization_id, role = scope
        self._require_writer(role)
        address = await organizations_repo.get_address(
            self.db, organization_id=organization_id, address_id=address_id
        )
        if address is None:
            raise OrganizationAddressError(
                code="ADDRESS_NOT_FOUND",
                status_code=404,
                title="Адрес не найден",
                detail="Адрес не найден в текущей организации",
            )
        new_kind = str(changes.get("kind", address.kind))
        new_line = str(changes.get("address_line", address.address_line))
        if new_kind != address.kind or new_line != address.address_line:
            duplicate = await organizations_repo.find_same_address(
                self.db,
                organization_id=organization_id,
                kind=new_kind,
                address_line=new_line,
                exclude_id=address.id,
            )
            if duplicate is not None:
                raise OrganizationAddressError(
                    code="ADDRESS_DUPLICATE",
                    status_code=409,
                    title="Адрес уже существует",
                    detail="Адрес с таким типом и строкой уже есть в адресной книге",
                )
        if changes.get("is_default"):
            await organizations_repo.clear_address_default(
                self.db,
                organization_id=organization_id,
                kind=new_kind,
                exclude_id=address.id,
            )
        for name, value in changes.items():
            setattr(address, name, value)
        await self.db.commit()
        await self.db.refresh(address)
        return address

    async def delete_address(self, user: User, *, address_id: uuid.UUID) -> None:
        scope = await self._resolve_scope(user)
        if scope is None:
            raise OrganizationAddressError(
                code="ADDRESS_NOT_FOUND",
                status_code=404,
                title="Адрес не найден",
                detail="Адрес не найден в текущей организации",
            )
        organization_id, role = scope
        self._require_writer(role)
        address = await organizations_repo.get_address(
            self.db, organization_id=organization_id, address_id=address_id
        )
        if address is None:
            raise OrganizationAddressError(
                code="ADDRESS_NOT_FOUND",
                status_code=404,
                title="Адрес не найден",
                detail="Адрес не найден в текущей организации",
            )
        await self.db.delete(address)
        await self.db.commit()


__all__ = [
    "InvalidMembershipTargetError",
    "InvalidOrganizationSelectionError",
    "LastOwnerProtectionError",
    "MembershipConflictError",
    "MembershipNotFoundError",
    "MembershipTargetNotFoundError",
    "OrganizationAddressError",
    "OrganizationAddressService",
    "OrganizationContext",
    "OrganizationContextService",
    "OrganizationManagementError",
    "OrganizationManagementService",
    "OrganizationMembershipContext",
    "OrganizationNotFoundError",
    "StaleMembershipVersionError",
]
