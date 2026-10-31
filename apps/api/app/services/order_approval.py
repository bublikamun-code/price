"""Виза OWNER над заявками организации (этап 6 роадмапа, §16 п.42).

Отдельный use-case (не раздувая services/order.py): approve/reject — только
активный OWNER организации заказа, принимается только из ``PENDING`` живой
заявки. Идемпотентность — машинным состоянием: повторный approve на
``APPROVED`` возвращает заказ без изменения (200 no-op), поэтому
``Idempotency-Key`` (в отличие от POST /orders) не применяется — действие не
создаёт ресурса. ``REJECTED`` терминален.

Заморозка (§16 п.42 п.7): PENDING-заявка уже снапшотнута при создании (§9) —
виза цены не пересчитывает и остатки не резервирует; ``version += 1`` и
аудит ``order.approve``/``order.reject``.

Сервис НЕ коммитит транзакцию — только ``flush`` (паттерн services/order.py);
in-app уведомление автору создаётся в той же транзакции, SSE-публикация —
роутером после коммита (``publish_visa_notification``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ApprovalStatus, OrderStatus, OrganizationRole
from app.models.order import Order
from app.models.system import AuditLog, Notification
from app.repositories import notifications as notifications_repo
from app.repositories import orders as orders_repo
from app.repositories import organizations as organizations_repo
from app.services.email import format_order_no
from app.services.notification_events import notification_payload, publish_notification
from app.services.notifications import (
    build_order_approved_text,
    build_order_rejected_text,
)
from app.services.order import (
    ApprovalForbiddenError,
    ApprovalNotPendingError,
    ApprovalTerminalError,
    OrderNotFoundError,
    StaleResourceVersionError,
)


class OrderApprovalService:
    """Approve/reject заявки активным OWNER организации (§16 п.42 п.6)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # In-app уведомление автору о визе; публикация в SSE ПОСЛЕ коммита.
        self.visa_notification: Notification | None = None

    async def _load_order_for_owner(
        self, owner, order_id: uuid.UUID
    ) -> Order:
        """Заказ существует и владелец — активный OWNER его организации.

        Не-участник организации получает 404 (существование чужих заявок не
        раскрывается, §16 п.42); участник не-OWNER — 403. Legacy-заявка без
        организации визы не имеет в принципе → 404 для всех.
        """
        order = await orders_repo.get_order(self.db, order_id=order_id)
        if order is None or order.organization_id is None:
            raise OrderNotFoundError("Заявка не найдена")
        membership = await organizations_repo.get_membership(
            self.db,
            organization_id=order.organization_id,
            user_id=owner.id,
        )
        if membership is None or not membership.is_active:
            raise OrderNotFoundError("Заявка не найдена")
        if membership.role is not OrganizationRole.OWNER:
            raise ApprovalForbiddenError(
                "Визу ставит только OWNER организации"
            )
        return order

    @staticmethod
    def _ensure_visable(order: Order) -> None:
        """Заявка живая и её гейт согласования — PENDING (§16 п.42 п.6).

        Виза принимается только из PENDING (§6 «Согласование заявок (v2)»):
        REJECTED терминален, APPROVED/NOT_REQUIRED — 409 (решение APPROVED
        не переписывается обратной визой, зеркально no-op-подходу approve).
        """
        if order.status is OrderStatus.CANCELLED:
            raise ApprovalNotPendingError("Заявка отменена — виза недоступна")
        if order.approval_status is ApprovalStatus.REJECTED:
            raise ApprovalTerminalError(
                "Заявка отклонена — решение окончательное"
            )
        if order.approval_status is not ApprovalStatus.PENDING:
            raise ApprovalNotPendingError(
                "Заявка не ожидает согласования"
            )

    async def approve_order(
        self,
        owner,
        order_id: uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> Order:
        order = await self._load_order_for_owner(owner, order_id)
        if expected_version is not None and order.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, актуальная версия {order.version}"
            )
        if order.approval_status is ApprovalStatus.APPROVED:
            # Идемпотентность машинным состоянием: no-op 200 без new version.
            return order
        self._ensure_visable(order)

        before = {
            "approval_status": order.approval_status.value,
            "version": order.version,
        }
        order.approval_status = ApprovalStatus.APPROVED
        order.approved_by = owner.id
        order.approved_at = datetime.now(timezone.utc)
        order.version += 1
        self.db.add(
            AuditLog(
                actor_id=owner.id,
                action="order.approve",
                target_type="order",
                target_id=order.id,
                before=before,
                after={
                    "approval_status": ApprovalStatus.APPROVED.value,
                    "approved_by": str(owner.id),
                    "version": order.version,
                },
            )
        )
        self.visa_notification = await notifications_repo.create_notification(
            self.db,
            type="ORDER_APPROVED",
            title="Заявка согласована",
            body=build_order_approved_text(format_order_no(order.seq)),
            user_id=order.client_id,
            channel=["inapp"],
            payload={
                "order_id": str(order.id),
                "order_number": format_order_no(order.seq),
                "approval_status": ApprovalStatus.APPROVED.value,
            },
        )
        await self.db.flush()
        return order

    async def reject_order(self, owner, order_id: uuid.UUID, *, reason: str) -> Order:
        order = await self._load_order_for_owner(owner, order_id)
        if order.approval_status is ApprovalStatus.REJECTED:
            # Причина уже зафиксирована и не переписывается.
            raise ApprovalTerminalError(
                "Заявка уже отклонена — решение окончательное"
            )
        self._ensure_visable(order)

        before = {
            "approval_status": order.approval_status.value,
            "version": order.version,
        }
        order.approval_status = ApprovalStatus.REJECTED
        order.approved_by = owner.id
        order.approved_at = datetime.now(timezone.utc)
        order.rejection_reason = reason
        order.version += 1
        self.db.add(
            AuditLog(
                actor_id=owner.id,
                action="order.reject",
                target_type="order",
                target_id=order.id,
                before=before,
                after={
                    "approval_status": ApprovalStatus.REJECTED.value,
                    "approved_by": str(owner.id),
                    "rejection_reason": reason,
                    "version": order.version,
                },
            )
        )
        self.visa_notification = await notifications_repo.create_notification(
            self.db,
            type="ORDER_REJECTED",
            title="Заявка отклонена",
            body=build_order_rejected_text(format_order_no(order.seq), reason),
            user_id=order.client_id,
            channel=["inapp"],
            payload={
                "order_id": str(order.id),
                "order_number": format_order_no(order.seq),
                "approval_status": ApprovalStatus.REJECTED.value,
                "rejection_reason": reason,
            },
        )
        await self.db.flush()
        return order

    def publish_visa_notification(self) -> None:
        """SSE-событие визы автору — ПОСЛЕ коммита роутером (fail-open)."""
        notif = self.visa_notification
        if notif is None:
            return
        publish_notification(notification_payload(notif), user_id=notif.user_id)


__all__ = ["OrderApprovalService"]
