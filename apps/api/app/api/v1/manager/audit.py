"""Роутер журнала аудита (/api/v1/manager/audit). См. §5, §6, §16 п.19."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.audit import fetch_audit
from app.schemas import MetaPage
from app.schemas.audit import AuditPage, AuditRead

router = APIRouter(prefix="/audit", tags=["manager:audit"])


@router.get("", response_model=AuditPage)
async def list_audit(
    action: str | None = Query(default=None, description="Фильтр по действию"),
    actor_id: uuid.UUID | None = Query(default=None, description="Фильтр по актёру"),
    target_type: str | None = Query(default=None, description="Фильтр по типу цели"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _manager: User = Depends(require_role(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> AuditPage:
    limit, offset = per_page, (page - 1) * per_page
    rows, total = await fetch_audit(
        db, action=action, actor_id=actor_id, target_type=target_type,
        limit=limit, offset=offset,
    )
    data = [
        AuditRead(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_email=actor_email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            before=entry.before,
            after=entry.after,
            created_at=entry.created_at,
        )
        for entry, actor_email in rows
    ]
    return AuditPage(data=data, meta=MetaPage(page=page, per_page=per_page, total=total))
