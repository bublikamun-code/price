"""Read and atomic write helpers for organization context and memberships."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrganizationRole
from app.models.organization import Organization, OrganizationMembership
from app.models.user import User


@dataclass(frozen=True)
class MembershipRecord:
    membership: OrganizationMembership
    organization: Organization


@dataclass(frozen=True)
class MemberRecord:
    membership: OrganizationMembership
    user: User


async def fetch_memberships(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[MembershipRecord]:
    result = await db.execute(
        select(OrganizationMembership, Organization)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .where(OrganizationMembership.user_id == user_id)
        .order_by(
            OrganizationMembership.is_primary.desc(),
            OrganizationMembership.created_at,
            Organization.legal_name,
        )
    )
    return [MembershipRecord(membership=m, organization=o) for m, o in result.all()]


async def has_active_membership(
    db: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> bool:
    return bool(
        await db.scalar(
            select(OrganizationMembership.organization_id)
            .join(
                Organization,
                Organization.id == OrganizationMembership.organization_id,
            )
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.is_active.is_(True),
                Organization.is_active.is_(True),
            )
            .limit(1)
        )
    )


async def get_organization(
    db: AsyncSession, *, organization_id: uuid.UUID, for_update: bool = False
) -> Organization | None:
    stmt = select(Organization).where(Organization.id == organization_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def list_organizations(
    db: AsyncSession, *, query: str | None = None
) -> list[Organization]:
    stmt = select(Organization)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(
            Organization.legal_name.ilike(pattern)
            | Organization.display_name.ilike(pattern)
        )
    result = await db.execute(stmt.order_by(Organization.legal_name, Organization.id))
    return list(result.scalars().all())


def _search_pattern(query: str) -> str:
    escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _cursor_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def fetch_organizations_page(
    db: AsyncSession,
    *,
    q: str | None = None,
    sort: str = "legalName",
    limit: int = 51,
    after: dict[str, str] | None = None,
) -> list[Organization]:
    """Fetch an organization keyset page without materializing the full list."""
    stmt = select(Organization)
    if q and q.strip():
        pattern = _search_pattern(q)
        stmt = stmt.where(
            Organization.legal_name.ilike(pattern, escape="\\")
            | Organization.display_name.ilike(pattern, escape="\\")
            | Organization.tax_id.ilike(pattern, escape="\\")
        )

    if sort in {"createdAt", "-createdAt"}:
        value_column = Organization.created_at
        parse_value = _cursor_datetime
    else:
        value_column = Organization.legal_name
        parse_value = str
    descending = sort.startswith("-")
    id_order = Organization.id.desc() if descending else Organization.id.asc()
    stmt = stmt.order_by(value_column.desc() if descending else value_column.asc(), id_order)

    if after is not None:
        last_id = uuid.UUID(after["id"])
        last_value = parse_value(after["value"])
        primary = (
            value_column < last_value
            if descending
            else value_column > last_value
        )
        tie_id = Organization.id < last_id if descending else Organization.id > last_id
        stmt = stmt.where(or_(primary, (value_column == last_value) & tie_id))

    result = await db.execute(stmt.limit(limit))
    return list(result.scalars().all())


async def get_user(db: AsyncSession, *, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_membership(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    for_update: bool = False,
) -> OrganizationMembership | None:
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def list_members(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> list[MemberRecord]:
    result = await db.execute(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(User.full_name, User.email, User.id)
    )
    return [MemberRecord(membership=m, user=u) for m, u in result.all()]


async def fetch_members_page(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    q: str | None = None,
    sort: str = "fullName",
    limit: int = 51,
    after: dict[str, str] | None = None,
) -> list[MemberRecord]:
    """Fetch a member keyset page with database-side search and ordering."""
    stmt = (
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(OrganizationMembership.organization_id == organization_id)
    )
    if q and q.strip():
        pattern = _search_pattern(q)
        stmt = stmt.where(
            User.email.ilike(pattern, escape="\\")
            | User.full_name.ilike(pattern, escape="\\")
        )

    if sort in {"createdAt", "-createdAt"}:
        value_column = OrganizationMembership.created_at
        parse_value = _cursor_datetime
    elif sort in {"email", "-email"}:
        value_column = User.email
        parse_value = str
    else:
        value_column = User.full_name
        parse_value = str
    descending = sort.startswith("-")
    id_order = User.id.desc() if descending else User.id.asc()
    stmt = stmt.order_by(value_column.desc() if descending else value_column.asc(), id_order)

    if after is not None:
        last_id = uuid.UUID(after["id"])
        last_value = parse_value(after["value"])
        primary = value_column < last_value if descending else value_column > last_value
        tie_id = User.id < last_id if descending else User.id > last_id
        stmt = stmt.where(or_(primary, (value_column == last_value) & tie_id))

    result = await db.execute(stmt.limit(limit))
    return [MemberRecord(membership=membership, user=user) for membership, user in result.all()]


async def count_active_owners(
    db: AsyncSession, *, organization_id: uuid.UUID
) -> int:
    return int(
        await db.scalar(
            select(func.count(OrganizationMembership.user_id))
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == OrganizationRole.OWNER,
                OrganizationMembership.is_active.is_(True),
            )
        )
        or 0
    )


async def add_membership(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: OrganizationRole,
    is_active: bool,
    is_primary: bool,
) -> OrganizationMembership:
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        is_active=is_active,
        is_primary=is_primary,
    )
    db.add(membership)
    await db.flush()
    return membership


async def update_membership_atomic(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_version: int,
    role: OrganizationRole,
    is_active: bool,
    is_primary: bool,
) -> bool:
    """Update only the expected membership version and return whether it matched."""
    result = await db.execute(
        update(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.version == expected_version,
        )
        .values(
            role=role,
            is_active=is_active,
            is_primary=is_primary,
            version=OrganizationMembership.version + 1,
            updated_at=func.now(),
        )
    )
    return result.rowcount == 1


async def clear_active_organization_for_user(
    db: AsyncSession, *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> bool:
    result = await db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.active_organization_id == organization_id,
        )
        .values(active_organization_id=None)
    )
    return result.rowcount == 1


__all__ = [
    "MemberRecord",
    "MembershipRecord",
    "add_membership",
    "clear_active_organization_for_user",
    "count_active_owners",
    "fetch_members_page",
    "fetch_memberships",
    "fetch_organizations_page",
    "get_membership",
    "get_organization",
    "get_user",
    "has_active_membership",
    "list_members",
    "list_organizations",
    "update_membership_atomic",
]
