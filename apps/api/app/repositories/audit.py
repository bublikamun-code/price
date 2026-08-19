"""Репозиторий журнала аудита. См. §5, §6, §11."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import AuditLog
from app.models.user import User


async def create_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
    )
    db.add(entry)
    await db.flush()
    return entry


def _apply_filters(stmt, *, action: str | None, actor_id: uuid.UUID | None, target_type: str | None):
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    return stmt


async def fetch_audit(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Журнал аудита (новые сначала) с email актёра. Возвращает list[Row] + total."""
    stmt = _apply_filters(
        select(AuditLog, User.email.label("actor_email")).outerjoin(
            User, User.id == AuditLog.actor_id
        ),
        action=action,
        actor_id=actor_id,
        target_type=target_type,
    ).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)

    total_stmt = _apply_filters(
        select(func.count(AuditLog.id)),
        action=action,
        actor_id=actor_id,
        target_type=target_type,
    )
    total = int(await db.scalar(total_stmt) or 0)
    return list(res.all()), total
