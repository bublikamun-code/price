"""Сервис счёта на оплату. См. ARCHITECTURE_PLAN.md §6, §10, §16 п.40.

Ключевые инварианты канона:
  * счёт 1:1 с заказом (``invoices.order_id UNIQUE``): второй → 409
    ``INVOICE_ALREADY_EXISTS``, заказ ``CANCELLED`` → 409 ``ORDER_NOT_INVOICABLE``;
  * суммы заморожены — копия ``orders.total_amount``/``currency_code`` на
    момент выставления, пересчёта по курсу НБ РБ здесь нет;
  * номер ``СЧ-YYYY-NNNNNN`` из ``invoices_seq_seq``, фиксируется в колонке и
    не пересчитывается;
  * состояние PDF — колонка ``pdf_status``, а не Redis-job: ошибка рендера →
    ``FAILED`` + перерендер; задача ставится ПОСЛЕ коммита и fail-open;
  * ``If-Match`` на счёте сверяет ``invoices.version``, а не версию заказа.

Сервис НЕ коммитит транзакцию — только ``flush``; коммит выполняет роутер
(как в services/order.py). Доменные ошибки содержат стабильный машинный код и
преобразуются роутером в Problem Details.
"""
import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import (
    FileAssetType,
    FileVisibility,
    InvoicePdfStatus,
    InvoiceStatus,
    OrderStatus,
    UserRole,
)
from app.models.file import FileAsset
from app.models.invoice import Invoice
from app.models.order import Order, OrderIdempotency
from app.repositories import audit as audit_repo
from app.repositories import invoices as invoices_repo
from app.repositories import orders as orders_repo
from app.repositories import organizations as organizations_repo
from app.services.organizations import OrganizationContextService

log = get_logger("app.services.invoice")

# Формат печатного номера счёта (§16 п.40 п.2). Год — только отображение:
# последовательность сквозная и по году не сбрасывается.
INVOICE_NUMBER_TEMPLATE = "СЧ-{year}-{seq:06d}"


class InvoiceError(Exception):
    """Доменная ошибка счёта с машинным кодом для API v2."""

    code = "INVOICE_ERROR"
    status_code = 400
    title = "Ошибка счёта"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class InvoiceNotFoundError(InvoiceError):
    code = "INVOICE_NOT_FOUND"
    status_code = 404
    title = "Счёт не найден"


class InvoiceAlreadyExistsError(InvoiceError):
    """1:1 с заказом: второй счёт по тому же заказу невозможен."""

    code = "INVOICE_ALREADY_EXISTS"
    status_code = 409
    title = "Счёт по заказу уже выставлен"


class OrderNotInvoicableError(InvoiceError):
    code = "ORDER_NOT_INVOICABLE"
    status_code = 409
    title = "По заказу нельзя выставить счёт"


class OrderNotFoundError(InvoiceError):
    """Заказ не найден — тот же код, что у заказов v2 (services/order.py)."""

    code = "ORDER_NOT_FOUND"
    status_code = 404
    title = "Заказ не найден"


class InvoicePdfInProgressError(InvoiceError):
    code = "INVOICE_PDF_IN_PROGRESS"
    status_code = 409
    title = "PDF счёта уже рендерится"


class InvoicePdfNotReadyError(InvoiceError):
    code = "INVOICE_PDF_NOT_READY"
    status_code = 409
    title = "PDF счёта не готов"


class IdempotencyKeyReusedError(InvoiceError):
    code = "IDEMPOTENCY_KEY_REUSED"
    status_code = 409
    title = "Ключ идемпотентности уже использован"


class StaleResourceVersionError(InvoiceError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Ресурс изменился"


class OrganizationBillingNotFoundError(InvoiceError):
    code = "ORGANIZATION_NOT_FOUND"
    status_code = 404
    title = "Организация не найдена"


def invoice_request_fingerprint(
    *, user_id: uuid.UUID, order_id: uuid.UUID
) -> str:
    """SHA-256 канонического запроса выставления счёта.

    У POST /manager/orders/{orderId}/invoice нет тела — fingerprint определяется
    актором и заказом, поэтому тот же ключ на другом заказе даёт
    ``IDEMPOTENCY_KEY_REUSED``, а не тихий возврат чужого счёта.
    """
    canonical = {
        "actor_user_id": str(user_id),
        "order_id": str(order_id),
        "endpoint": "/api/v2/manager/orders/{orderId}/invoice",
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def format_invoice_number(*, seq: int, issued_at: datetime) -> str:
    """``СЧ-2026-000042`` (§16 п.40 п.2)."""
    return INVOICE_NUMBER_TEMPLATE.format(year=issued_at.year, seq=seq)


def enqueue_invoice_pdf(invoice_id: uuid.UUID) -> None:
    """Поставить задачу рендера PDF счёта (fire-and-forget).

    Fail-open по образцу ``services.email.queue_email``: сбой брокера не должен
    ломать выдачу счёта — счёт уже записан, а ``pdf_status=PENDING`` явно
    покажет в UI, что PDF ещё не готов и его можно перерендерить.
    """
    from app.tasks.export_invoice_pdf import render_invoice_pdf

    try:
        render_invoice_pdf.delay(str(invoice_id))
    except Exception as exc:  # noqa: BLE001 — брокер недоступен, счёт уже выдан
        log.warning(
            "invoice.pdf_enqueue_failed", invoice=str(invoice_id), error=str(exc)
        )


class InvoiceService:
    """Выставление, смена статуса, рендер и выдача счёта."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.organizations = OrganizationContextService(db)

    # --------------------------------------------------------- idempotency
    # Отдельной таблицы для счёта не заводим: сущность ``OrderIdempotency``
    # привязана к заказу (order_id, CASCADE), а счёт существует ровно один на
    # заказ — этого достаточно, чтобы повтор с тем же ключом вернул тот же
    # счёт. Новый ключ на тот же заказ даёт 409 INVOICE_ALREADY_EXISTS.
    async def request_fingerprint(
        self, user, *, order_id: uuid.UUID
    ) -> str:
        return invoice_request_fingerprint(user_id=user.id, order_id=order_id)

    async def find_idempotent_invoice(
        self, user, *, idempotency_key: str, request_hash: str
    ) -> Invoice | None:
        record = await orders_repo.get_idempotency_record(
            self.db, user_id=user.id, idempotency_key=idempotency_key
        )
        if record is None:
            return None
        if record.request_hash != request_hash:
            raise IdempotencyKeyReusedError(
                "Ключ Idempotency-Key уже использован с другими данными"
            )
        if record.order_id is None:
            # Ключ забронирован, но заказ ещё не проставлен — конкурентный
            # запрос в этой же транзакции ещё не завершён.
            raise IdempotencyKeyReusedError(
                "Счёт с этим ключом ещё выставляется; повторите запрос позже"
            )
        invoice = await invoices_repo.get_invoice_by_order(
            self.db, order_id=record.order_id
        )
        if invoice is None:
            raise IdempotencyKeyReusedError(
                "Ключ Idempotency-Key уже использован, но счёт по заказу не найден"
            )
        return invoice

    async def reserve_idempotency(
        self, user, *, idempotency_key: str, request_hash: str
    ) -> OrderIdempotency | None:
        """Резервирует ключ; None означает конкурентный запрос с тем же ключом."""
        try:
            async with self.db.begin_nested():
                record = await orders_repo.add_idempotency_record(
                    self.db,
                    record=OrderIdempotency(
                        user_id=user.id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    ),
                )
            return record
        except IntegrityError:
            return None

    # -------------------------------------------------------------- issue
    async def issue(
        self, manager, order_id: uuid.UUID
    ) -> Invoice:
        """Выставить счёт по заказу (менеджер). Не коммитит транзакцию."""
        if manager.role not in {UserRole.MANAGER, UserRole.ADMIN}:
            raise InvoiceError("Выставление счёта доступно только менеджерам")

        order = await orders_repo.get_order(self.db, order_id=order_id)
        if order is None:
            raise OrderNotFoundError(f"Заказ {order_id} не найден")
        if order.status == OrderStatus.CANCELLED:
            raise OrderNotInvoicableError(
                "По отменённому заказу счёт не выставляется"
            )

        existing = await invoices_repo.get_invoice_by_order(
            self.db, order_id=order.id
        )
        if existing is not None:
            raise InvoiceAlreadyExistsError(
                f"По заказу {order.id} счёт уже выставлен: {existing.number}"
            )

        issued_at = datetime.now(UTC)
        seq = await invoices_repo.next_invoice_seq(self.db)
        invoice = Invoice(
            order_id=order.id,
            seq=seq,
            number=format_invoice_number(seq=seq, issued_at=issued_at),
            status=InvoiceStatus.ISSUED,
            pdf_status=InvoicePdfStatus.PENDING,
            # Заморозка (§16 п.40 п.3): копия суммы и валюты заказа.
            total_amount=order.total_amount,
            currency_code=order.currency_code,
            issued_at=issued_at,
            created_by=manager.id,
            version=1,
        )
        try:
            # Savepoint: гонка двух менеджеров за одним заказом ломает
            # uq_invoices_order_id. Откатываем только savepoint — транзакцию
            # роутера (в ней уже лежит резерв Idempotency-Key) не трогаем.
            async with self.db.begin_nested():
                invoice = await invoices_repo.create_invoice(
                    self.db, invoice=invoice
                )
        except IntegrityError as exc:
            raise InvoiceAlreadyExistsError(
                f"По заказу {order.id} счёт уже выставлен"
            ) from exc

        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="invoice.issue",
            target_type="invoice",
            target_id=invoice.id,
            before=None,
            after={
                "orderId": str(order.id),
                "number": invoice.number,
                "seq": invoice.seq,
                "status": invoice.status.value,
                "pdfStatus": invoice.pdf_status.value,
                "total": str(invoice.total_amount),
                "currency": invoice.currency_code,
                "version": invoice.version,
            },
        )
        return invoice

    # --------------------------------------------------------- pdf render
    async def regenerate_pdf(self, manager, invoice_id: uuid.UUID) -> Invoice:
        """Перерендерить PDF: после FAILED или после правки реквизитов (§6)."""
        invoice = await self._require_invoice(invoice_id)
        if invoice.pdf_status == InvoicePdfStatus.PENDING:
            raise InvoicePdfInProgressError(
                "PDF счёта уже рендерится"
            )
        invoice.pdf_status = InvoicePdfStatus.PENDING
        await self.db.flush()
        return invoice

    # ------------------------------------------------------------- status
    async def change_status(
        self,
        manager,
        invoice_id: uuid.UUID,
        *,
        new_status: InvoiceStatus,
        expected_version: int,
    ) -> Invoice:
        """Смена статуса счёта. If-Match сверяет версию СЧЁТА (§16 п.40 п.8)."""
        # ``V2Model`` объявлен с ``use_enum_values=True``, поэтому из роутера
        # статус приходит строкой — нормализуем до enum явно.
        new_status = InvoiceStatus(new_status)
        invoice = await self._require_invoice(invoice_id)
        if invoice.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, "
                f"актуальная версия {invoice.version}"
            )
        before = {
            "status": invoice.status.value,
            "pdfStatus": invoice.pdf_status.value,
            "version": invoice.version,
        }
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="invoice.update",
            target_type="invoice",
            target_id=invoice.id,
            before=before,
            after={
                "status": new_status.value,
                "pdfStatus": invoice.pdf_status.value,
                "version": invoice.version + 1,
            },
        )
        invoice.status = new_status
        invoice.version += 1
        await self.db.flush()
        return invoice

    # ---------------------------------------------------------------- read
    async def get_for_order(self, user, order_id: uuid.UUID) -> Invoice:
        """Счёт по заказу: клиент — только свой, менеджер — любой (§6)."""
        order = await self._visible_order(user, order_id)
        invoice = await invoices_repo.get_invoice_by_order(
            self.db, order_id=order.id
        )
        if invoice is None:
            raise InvoiceNotFoundError(f"По заказу {order.id} счёт не выставлен")
        return invoice

    async def invoice_for_download(self, user, invoice_id: uuid.UUID) -> Invoice:
        """Счёт для выдачи PDF байтами; нет доступа/нет счёта → 404."""
        invoice = await invoices_repo.get_invoice(self.db, invoice_id=invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError("Счёт не найден")
        await self._visible_order(user, invoice.order_id)
        return invoice

    async def organization_for_invoice(self, invoice: Invoice):
        """Организация покупателя — для проекции реквизитов в InvoiceOut."""
        order = await orders_repo.get_order(self.db, order_id=invoice.order_id)
        if order is None or order.organization_id is None:
            return None
        return await organizations_repo.get_organization(
            self.db, organization_id=order.organization_id
        )

    # ------------------------------------------- реквизиты организации (PATCH)
    async def update_organization_billing(
        self, manager, organization_id: uuid.UUID, *, expected_version: int, patch
    ):
        """Реквизиты организации для счёта (§16 п.40 п.4): ``If-Match`` + аудит.

        Обновляются только переданные поля; ``None`` означает «не трогать».
        Явного сброса поля в контракте нет — чтобы стереть реквизит, менеджер
        присылает пустую строку, которая сохраняется как есть.
        """
        organization = await organizations_repo.get_organization(
            self.db, organization_id=organization_id, for_update=True
        )
        if organization is None:
            raise OrganizationBillingNotFoundError("Организация не найдена")
        if organization.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, "
                f"актуальная версия {organization.version}"
            )

        fields = (
            "tax_id",
            "legal_address",
            "legal_phone",
            "legal_email",
            "bank_name",
            "bank_code",
            "bank_account",
        )
        before = {
            name: getattr(organization, name)
            for name in fields
            if getattr(patch, name, None) is not None
        }
        for name in fields:
            value = getattr(patch, name, None)
            if value is not None:
                setattr(organization, name, value)
        organization.version += 1
        await self.db.flush()
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="organization.update",
            target_type="organization",
            target_id=organization.id,
            before=before,
            after={
                name: getattr(organization, name)
                for name in fields
                if name in before or getattr(patch, name, None) is not None
            },
        )
        # ``updated_at`` помечен как просроченный: его обновляет
        # ``onupdate=func.now()`` на стороне БД, и после flush значение есть
        # только в сервере. Без refresh проекция OrganizationDetail упала бы
        # в MissingGreenlet (синхронный доступ к ленивому IO). Образец —
        # ``api/v2/orders.py`` после мутации заказа.
        await self.db.refresh(organization)
        return organization

    # -------------------------------------------------------------- helpers
    async def _require_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = await invoices_repo.get_invoice(self.db, invoice_id=invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError("Счёт не найден")
        return invoice

    async def _visible_order(self, user, order_id: uuid.UUID) -> Order:
        """Заказ в коммерческом scope вызывающего: менеджер — любой."""
        if user.role in {UserRole.MANAGER, UserRole.ADMIN}:
            order = await orders_repo.get_order(self.db, order_id=order_id)
            if order is None:
                raise InvoiceNotFoundError("Счёт не найден")
            return order

        order = await orders_repo.get_order(self.db, order_id=order_id)
        if order is None:
            # Несуществующий и чужой заказ неотличимы — 404, без утечки.
            raise InvoiceNotFoundError("Счёт не найден")
        context = await self.organizations.resolve(user)
        visible = (
            order.organization_id is not None
            and order.organization_id == context.organization_id
        ) or (order.organization_id is None and order.client_id == user.id)
        if not visible:
            raise InvoiceNotFoundError("Счёт не найден")
        return order


def invoice_pdf_asset(
    *,
    invoice: Invoice,
    order: Order,
    s3_key: str,
    size_bytes: int,
) -> FileAsset:
    """Собрать ``FileAsset`` для PDF счёта (создаёт его уже задача рендера).

    ``visibility=AUTHED`` (§10): файл не публичный — скачивание идёт байтами
    через ``GET /api/v2/orders/invoices/{id}/download`` после проверки доступа,
    никогда presigned (§16 п.37).
    """
    return FileAsset(
        type=FileAssetType.INVOICE_PDF,
        s3_key=s3_key,
        filename_display=f"{invoice.number}.pdf",
        content_type="application/pdf",
        size_bytes=size_bytes,
        order_id=order.id,
        visibility=FileVisibility.AUTHED,
    )


__all__ = [
    "InvoiceAlreadyExistsError",
    "InvoiceError",
    "InvoiceNotFoundError",
    "InvoicePdfInProgressError",
    "InvoicePdfNotReadyError",
    "InvoiceService",
    "IdempotencyKeyReusedError",
    "OrderNotInvoicableError",
    "OrderNotFoundError",
    "OrganizationBillingNotFoundError",
    "StaleResourceVersionError",
    "enqueue_invoice_pdf",
    "format_invoice_number",
    "invoice_request_fingerprint",
]
