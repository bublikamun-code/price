"""Сервис коммерческих предложений (КП). Этап 8 роадмапа.

docs/FEATURES_ROADMAP.md «Этап 8. Коммерческие предложения».

Ключевые инварианты:
  * жизненный цикл: DRAFT →(менеджер send)→ SENT →(клиент accept)→ ACCEPTED |
    (клиент reject)→ REJECTED | (beat/лениво, valid_until < now)→ EXPIRED;
    accept на не-SENT или истёкшем → 409;
  * правки (edit/delete/PDF-ключ) — только в DRAFT (QUOTE_NOT_DRAFT);
  * номер ``КП-YYYY-NNNNNN`` + ``seq`` присваиваются при SEND (nextval из
    ``quotes_seq_seq``, §16 п.9); у DRAFT номера нет — черновик не документ;
  * total в DRAFT пересчитывается при каждой правке («не заморожен»), при
    SEND фиксируется окончательно;
  * accept создаёт заявку с ЦЕНАМИ ИЗ КП (services/order.py::
    create_from_quote — без прайс-логики и скидок), Idempotency-Key обязателен,
    корзина не затрагивается;
  * клиент видит КП только своей активной организации (org-scope, 404 на
    чужое; DRAFT клиенту не виден вовсе). Публичных токен-ссылок нет;
  * PDF — СИНХРОННЫЙ рендер по запросу менеджера (без Celery): CPU-часть
    (weasyprint) выносится в поток через ``asyncio.to_thread``, как в
    tasks/export_invoice_pdf.py, DB-часть остаётся на event loop'е
    (AsyncSession не threadsafe — поэтому обёртка to_thread внутри сервиса,
    а не вокруг него в роутере);
  * уведомления in-app — в той же транзакции (NEW_QUOTE участникам org при
    send; QUOTE_ACCEPTED/QUOTE_REJECTED менеджеру-создателю при
    accept/reject); публикация в SSE — после коммита роутером (fail-open).

Сервис НЕ коммитит транзакцию — только ``flush``; коммит выполняет роутер
(как в services/invoice.py). Доменные ошибки содержат стабильный машинный код
и преобразуются роутером в Problem Details.
"""
import asyncio
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import (
    FileAssetType,
    FileVisibility,
    QuotePdfStatus,
    QuoteStatus,
    StockStatus,
)
from app.models.file import FileAsset
from app.models.order import Order, OrderIdempotency
from app.models.quote import Quote, QuoteItem
from app.models.system import Notification
from app.repositories import audit as audit_repo
from app.repositories import catalog as catalog_repo
from app.repositories import notifications as notifications_repo
from app.repositories import orders as orders_repo
from app.repositories import organizations as organizations_repo
from app.repositories import quotes as quotes_repo
from app.schemas.v2.orders import OrderDeliveryCreate
from app.services import storage
from app.services.notification_events import notification_payload, publish_notification
from app.services.notifications import (
    build_quote_accepted_text,
    build_quote_rejected_text,
    build_quote_sent_text,
)
from app.services.order import OrderService
from app.services.organizations import OrganizationContextService
from app.services.pricing import quantize_money

log = get_logger("app.services.quote")

# Формат печатного номера КП (этап 8). Год — только отображение:
# последовательность сквозная и по году не сбрасывается.
QUOTE_NUMBER_TEMPLATE = "КП-{year}-{seq:06d}"

# Верхняя граница позиций КП — та же, что у заявок v2 (OrderCreate.items).
QUOTE_MAX_ITEMS = 500

# Endpoint для fingerprint идемпотентности accept (§11).
QUOTE_ACCEPT_ENDPOINT = "/api/v2/quotes/{id}/accept"


class QuoteError(Exception):
    """Доменная ошибка КП с машинным кодом для API v2."""

    code = "QUOTE_ERROR"
    status_code = 400
    title = "Ошибка коммерческого предложения"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class QuoteNotFoundError(QuoteError):
    code = "QUOTE_NOT_FOUND"
    status_code = 404
    title = "Коммерческое предложение не найдено"


class QuoteNotDraftError(QuoteError):
    """Правка/удаление доступна только в DRAFT."""

    code = "QUOTE_NOT_DRAFT"
    status_code = 409
    title = "КП больше не черновик"


class QuoteNotSentError(QuoteError):
    """accept на не-SENT (DRAFT) — КП ещё не отправлено клиенту."""

    code = "QUOTE_NOT_SENT"
    status_code = 409
    title = "КП не отправлено"


class QuoteExpiredError(QuoteError):
    """accept на истёкшем КП (valid_until < now, статус EXPIRED)."""

    code = "QUOTE_EXPIRED"
    status_code = 409
    title = "Срок действия КП истёк"


class QuoteStateChangedError(QuoteError):
    """По КП уже принято решение (ACCEPTED/REJECTED) — второй accept/reject."""

    code = "QUOTE_STATE_CHANGED"
    status_code = 409
    title = "Состояние КП изменилось"


class QuoteItemUnavailableError(QuoteError):
    """Позиция КП ссылается на несуществующий/удалённый товар (create/edit)."""

    code = "QUOTE_ITEM_UNAVAILABLE"
    status_code = 409
    title = "Позиция КП недоступна"


class ProductUnavailableError(QuoteError):
    """Товар архивный — нельзя включить в КП (create/edit; accept даёт тот же
    машинный код с 409 через services/order.py::QuoteProductUnavailableError)."""

    code = "PRODUCT_UNAVAILABLE"
    status_code = 409
    title = "Товар недоступен"


class QuoteValidUntilRequiredError(QuoteError):
    """send без valid_until — срок действия обязателен к отправке."""

    code = "QUOTE_VALID_UNTIL_REQUIRED"
    status_code = 400
    title = "Не указан срок действия КП"


class QuoteValidUntilInPastError(QuoteError):
    """send/edit с valid_until в прошлом."""

    code = "QUOTE_VALID_UNTIL_IN_PAST"
    status_code = 400
    title = "Срок действия КП в прошлом"


class IdempotencyKeyReusedError(QuoteError):
    code = "IDEMPOTENCY_KEY_REUSED"
    status_code = 409
    title = "Ключ идемпотентности уже использован"


class IdempotencyInProgressError(QuoteError):
    """Ключ зарезервирован, первый accept ещё в полёте — тот же machine-code,
    что у заказов/счётов v2 (services/order.py, services/invoice.py)."""

    code = "IDEMPOTENCY_IN_PROGRESS"
    status_code = 409
    title = "Принятие КП уже выполняется"


class StaleResourceVersionError(QuoteError):
    code = "STALE_RESOURCE_VERSION"
    status_code = 409
    title = "Ресурс изменился"


class OrganizationNotFoundError(QuoteError):
    code = "ORGANIZATION_NOT_FOUND"
    status_code = 404
    title = "Организация не найдена"


def format_quote_number(*, seq: int, sent_at: datetime) -> str:
    """``КП-2026-000042`` (этап 8)."""
    return QUOTE_NUMBER_TEMPLATE.format(year=sent_at.year, seq=seq)


def quote_accept_fingerprint(
    *, user_id: uuid.UUID, quote_id: uuid.UUID, delivery: OrderDeliveryCreate
) -> str:
    """SHA-256 канонического accept-запроса.

    Fingerprint определяется актором, КП, endpoint'ом и delivery-данными:
    тот же ключ с другим телом даёт ``IDEMPOTENCY_KEY_REUSED``, а не тихий
    replay чужой заявки.
    """
    canonical = {
        "actor_user_id": str(user_id),
        "quote_id": str(quote_id),
        "endpoint": QUOTE_ACCEPT_ENDPOINT,
        "delivery": delivery.model_dump(mode="json"),
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_utc(value: datetime | None) -> datetime | None:
    """Нормализация наивной даты в UTC (клиент мог прислать без tz)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _quote_total(items: list[QuoteItem]) -> Decimal:
    """Сумма позиций КП: quantize на позиции и на итог (§8 — деньги Decimal)."""
    total = Decimal(0)
    for item in items:
        total += quantize_money(item.unit_price) * int(item.qty)
    return quantize_money(total)


def quote_pdf_asset(*, quote: Quote, s3_key: str, size_bytes: int) -> FileAsset:
    """Собрать ``FileAsset`` для PDF КП (создаётся при синхронном рендере).

    ``visibility=AUTHED`` (§10) — как у PDF счёта: файл не публичный,
    скачивание идёт байтами через ``GET /api/v2/quotes/{id}/pdf/download``
    после проверки доступа, никогда presigned (§16 п.37). FK на КП у
    file_assets нет — связь живёт в ``quotes.pdf_file_asset_id``.
    """
    return FileAsset(
        type=FileAssetType.QUOTE_PDF,
        s3_key=s3_key,
        filename_display=f"{quote.number}.pdf",
        content_type="application/pdf",
        size_bytes=size_bytes,
        visibility=FileVisibility.AUTHED,
    )


def _render_quote_pdf_bytes(*, quote: Quote, items: list[QuoteItem], organization) -> bytes:
    """quote.j2 → HTML → A4 (weasyprint). Sync + ленивые импорты — CPU-часть
    вызывается через ``asyncio.to_thread`` и только в момент рендера."""
    from app.core.pdf import write_pdf
    from app.core.templates import render_pdf
    from app.schemas.v2.invoices import invoice_buyer, invoice_seller

    rows = []
    for index, item in enumerate(items, start=1):
        price = quantize_money(item.unit_price)
        rows.append(
            {
                "no": index,
                "sku": item.sku,
                "name": item.name,
                "qty": int(item.qty),
                "price": f"{price:.2f}",
                "amount": f"{quantize_money(price * int(item.qty)):.2f}",
            }
        )

    html = render_pdf(
        "quote.j2",
        number=quote.number,
        sent_at=(
            quote.updated_at.strftime("%d.%m.%Y")
            if quote.updated_at is not None
            else ""
        ),
        valid_until=(
            quote.valid_until.strftime("%d.%m.%Y")
            if quote.valid_until is not None
            else None
        ),
        currency=quote.currency_code or "BYN",
        total=f"{quantize_money(quote.total_amount):.2f}",
        rows=rows,
        buyer=invoice_buyer(organization),
        seller=invoice_seller(),
    )
    return write_pdf(html)


class QuoteService:
    """Создание/правка КП, send/accept/reject, синхронный PDF-рендер."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.organizations = OrganizationContextService(db)
        # Заявки из КП создаёт OrderService.create_from_quote (общие хелперы:
        # локи товаров, снапшоты, гейт согласования §16 п.42).
        self.orders = OrderService(db)
        # In-app уведомление accept/reject менеджеру-создателю; публикуется
        # роутером ПОСЛЕ коммита (publish_status_notification, fail-open).
        self.status_notification: Notification | None = None
        # In-app NEW_QUOTE участникам организации (send); публикуется роутером
        # после коммита — publish_quote_notifications().
        self.quote_notifications: list[Notification] = []

    def publish_quote_notifications(self) -> None:
        """SSE-события NEW_QUOTE (send) — fail-open, после коммита роутера.

        Пустой список (send не звали / replay-путь) — no-op.
        """
        for notif in self.quote_notifications:
            publish_notification(notification_payload(notif), user_id=notif.user_id)

    # --------------------------------------------------------- idempotency
    # Отдельной таблицы для accept не заводим: OrderIdempotency привязана к
    # заказу (order_id CASCADE), accept создаёт ровно один заказ на КП —
    # этого достаточно, чтобы повтор с тем же ключом вернул ту же заявку.
    async def find_idempotent_order(
        self, user, *, idempotency_key: str, request_hash: str
    ) -> Order | None:
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
            # accept ещё не завершён (симметрично заказам/счётам v2).
            raise IdempotencyInProgressError(
                "Заявка по этому ключу ещё создаётся; повторите запрос позже"
            )
        return await self.orders.get(user, record.order_id, as_manager=False)

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

    # -------------------------------------------------------------- create
    async def create(self, manager, payload) -> Quote:
        """Создать DRAFT КП (менеджер). total — сумма позиций, не заморожен."""
        organization = await organizations_repo.get_organization(
            self.db, organization_id=payload.organization_id
        )
        if organization is None:
            raise OrganizationNotFoundError("Организация не найдена")

        items = await self._validated_items(payload.items)
        quote = Quote(
            organization_id=organization.id,
            created_by=manager.id,
            status=QuoteStatus.DRAFT,
            valid_until=_ensure_utc(payload.valid_until),
            total_amount=_quote_total(items),
            currency_code="BYN",
            version=1,
            pdf_status=QuotePdfStatus.PENDING,
        )
        quote = await quotes_repo.create_quote(self.db, quote=quote, items=items)
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="quote.create",
            target_type="quote",
            target_id=quote.id,
            before=None,
            after={
                "organizationId": str(quote.organization_id),
                "status": quote.status.value,
                "itemsCount": len(items),
                "total": str(quote.total_amount),
                "currency": quote.currency_code,
                "version": quote.version,
            },
        )
        return quote

    # ---------------------------------------------------------------- edit
    async def edit(self, manager, quote_id: uuid.UUID, payload, *, expected_version: int) -> Quote:
        """Правка DRAFT (If-Match): замена позиций и/или valid_until."""
        quote = await self._require_quote(quote_id)
        if quote.status is not QuoteStatus.DRAFT:
            raise QuoteNotDraftError("Править можно только черновик КП")
        if quote.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, "
                f"актуальная версия {quote.version}"
            )
        before = {
            "status": quote.status.value,
            "validUntil": quote.valid_until.isoformat() if quote.valid_until else None,
            "total": str(quote.total_amount),
            "version": quote.version,
        }
        if payload.valid_until is not None:
            valid_until = _ensure_utc(payload.valid_until)
            if valid_until < datetime.now(UTC):
                raise QuoteValidUntilInPastError("Срок действия КП не может быть в прошлом")
            quote.valid_until = valid_until
        if payload.items is not None:
            items = await self._validated_items(payload.items)
            await quotes_repo.replace_items(self.db, quote=quote, items=items)
        # total в DRAFT не заморожен — пересчитывается при каждой правке.
        quote.total_amount = _quote_total(list(quote.items))
        quote.version += 1
        await self.db.flush()
        # ``updated_at`` обновляет ``onupdate=func.now()`` на стороне БД: после
        # flush значение есть только в сервере, и синхронный доступ в проекции
        # упал бы в MissingGreenlet. Образец — update_organization_billing
        # в services/invoice.py.
        await self.db.refresh(quote)
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="quote.edit",
            target_type="quote",
            target_id=quote.id,
            before=before,
            after={
                "status": quote.status.value,
                "validUntil": quote.valid_until.isoformat() if quote.valid_until else None,
                "total": str(quote.total_amount),
                "itemsCount": len(quote.items),
                "version": quote.version,
            },
        )
        return quote

    # -------------------------------------------------------------- delete
    async def delete(self, manager, quote_id: uuid.UUID) -> None:
        """Удалить DRAFT КП (204). Позиции удаляются каскадом."""
        quote = await self._require_quote(quote_id)
        if quote.status is not QuoteStatus.DRAFT:
            raise QuoteNotDraftError("Удалять можно только черновик КП")
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="quote.delete",
            target_type="quote",
            target_id=quote.id,
            before={
                "status": quote.status.value,
                "total": str(quote.total_amount),
                "version": quote.version,
            },
            after=None,
        )
        await self.db.delete(quote)
        await self.db.flush()

    # ---------------------------------------------------------------- send
    async def send(self, manager, quote_id: uuid.UUID, *, expected_version: int) -> Quote:
        """DRAFT → SENT: номер+seq, заморозка total, уведомление org, аудит."""
        quote = await self._require_quote(quote_id)
        if quote.status is not QuoteStatus.DRAFT:
            raise QuoteNotDraftError("Отправить можно только черновик КП")
        if quote.version != expected_version:
            raise StaleResourceVersionError(
                f"Ожидалась версия {expected_version}, "
                f"актуальная версия {quote.version}"
            )
        if quote.valid_until is None:
            raise QuoteValidUntilRequiredError(
                "Перед отправкой укажите срок действия КП (validUntil)"
            )
        valid_until = _ensure_utc(quote.valid_until)
        if valid_until < datetime.now(UTC):
            raise QuoteValidUntilInPastError("Срок действия КП не может быть в прошлом")

        sent_at = datetime.now(UTC)
        seq = await quotes_repo.next_quote_seq(self.db)
        quote.seq = seq
        quote.number = format_quote_number(seq=seq, sent_at=sent_at)
        # Заморозка (этап 8): дальше total не пересчитывается.
        quote.total_amount = _quote_total(list(quote.items))
        quote.status = QuoteStatus.SENT
        quote.version += 1
        await self.db.flush()
        await audit_repo.create_audit(
            self.db,
            actor_id=manager.id,
            action="quote.send",
            target_type="quote",
            target_id=quote.id,
            before={"status": QuoteStatus.DRAFT.value, "version": quote.version - 1},
            after={
                "status": quote.status.value,
                "number": quote.number,
                "seq": quote.seq,
                "total": str(quote.total_amount),
                "validUntil": quote.valid_until.isoformat(),
                "version": quote.version,
            },
        )
        # In-app NEW_QUOTE всем активным участникам организации — в той же
        # транзакции, что и send (уведомление атомарно факту). Публикация
        # в SSE — после коммита роутером (publish_quote_notifications).
        member_ids = await organizations_repo.list_active_member_user_ids(
            self.db, organization_id=quote.organization_id
        )
        for member_id in member_ids:
            self.quote_notifications.append(
                await notifications_repo.create_notification(
                    self.db,
                    type="NEW_QUOTE",
                    title="Новое коммерческое предложение",
                    body=build_quote_sent_text(
                        quote.number, quote.total_amount, quote.currency_code
                    ),
                    user_id=member_id,
                    channel=["inapp"],
                    payload={
                        "quote_id": str(quote.id),
                        "quote_number": quote.number,
                        "valid_until": quote.valid_until.isoformat(),
                        "amount": str(quote.total_amount),
                        "currency": quote.currency_code,
                    },
                )
            )
        # ``updated_at`` обновляет ``onupdate=func.now()`` на стороне БД: после
        # flush значение есть только в сервере — синхронный доступ в проекции
        # (quote_out в роутере) упал бы в MissingGreenlet. Образец —
        # update_organization_billing в services/invoice.py.
        await self.db.refresh(quote)
        return quote

    # -------------------------------------------------------------- accept
    async def accept(self, user, quote_id: uuid.UUID, *, delivery: OrderDeliveryCreate) -> Order:
        """SENT → ACCEPTED: заявка с ЦЕНАМИ ИЗ КП (Idempotency-Key — в роутере)."""
        await quotes_repo.expire_due(self.db)
        quote = await self._require_quote(quote_id)
        context = await self._context_for_quote(user, quote)
        if quote.status is QuoteStatus.EXPIRED:
            raise QuoteExpiredError("Срок действия КП истёк — принять его нельзя")
        if quote.status is QuoteStatus.DRAFT:
            raise QuoteNotSentError("КП ещё не отправлено клиенту")
        if quote.status is not QuoteStatus.SENT:
            raise QuoteStateChangedError("По этому КП уже принято решение")

        order = await self.orders.create_from_quote(
            user, quote, delivery=delivery, context=context
        )
        quote.status = QuoteStatus.ACCEPTED
        quote.version += 1
        await self.db.flush()
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="quote.accept",
            target_type="quote",
            target_id=quote.id,
            before={"status": QuoteStatus.SENT.value, "version": quote.version - 1},
            after={
                "status": quote.status.value,
                "orderId": str(order.id),
                "orderTotal": str(order.total_amount),
                "version": quote.version,
            },
        )
        # In-app менеджеру-создателю — в той же транзакции, что и accept.
        # SSE — после коммита роутером (publish_status_notification).
        if quote.created_by is not None:
            self.status_notification = await notifications_repo.create_notification(
                self.db,
                type="QUOTE_ACCEPTED",
                title="КП принято клиентом",
                body=build_quote_accepted_text(
                    quote.number or str(quote.id),
                    str(order.seq),
                ),
                user_id=quote.created_by,
                channel=["inapp"],
                payload={
                    "quote_id": str(quote.id),
                    "quote_number": quote.number,
                    "order_id": str(order.id),
                    "order_total": str(order.total_amount),
                    "currency": order.currency_code,
                },
            )
        return order

    # -------------------------------------------------------------- reject
    async def reject(self, user, quote_id: uuid.UUID) -> Quote:
        """SENT → REJECTED клиентом; повторный reject — 409."""
        await quotes_repo.expire_due(self.db)
        quote = await self._require_quote(quote_id)
        await self._context_for_quote(user, quote)
        if quote.status is QuoteStatus.EXPIRED:
            raise QuoteExpiredError("Срок действия КП истёк")
        if quote.status is QuoteStatus.DRAFT:
            raise QuoteNotSentError("КП ещё не отправлено клиенту")
        if quote.status is not QuoteStatus.SENT:
            raise QuoteStateChangedError("По этому КП уже принято решение")

        quote.status = QuoteStatus.REJECTED
        quote.version += 1
        await self.db.flush()
        await audit_repo.create_audit(
            self.db,
            actor_id=user.id,
            action="quote.reject",
            target_type="quote",
            target_id=quote.id,
            before={"status": QuoteStatus.SENT.value, "version": quote.version - 1},
            after={
                "status": quote.status.value,
                "version": quote.version,
            },
        )
        if quote.created_by is not None:
            self.status_notification = await notifications_repo.create_notification(
                self.db,
                type="QUOTE_REJECTED",
                title="КП отклонено клиентом",
                body=build_quote_rejected_text(quote.number or str(quote.id)),
                user_id=quote.created_by,
                channel=["inapp"],
                payload={
                    "quote_id": str(quote.id),
                    "quote_number": quote.number,
                },
            )
        # ``updated_at`` обновляет ``onupdate=func.now()`` на стороне БД: после
        # flush значение есть только в сервере — синхронный доступ в проекции
        # (quote_out в роутере) упал бы в MissingGreenlet. Образец —
        # update_organization_billing в services/invoice.py.
        await self.db.refresh(quote)
        return quote

    # ---------------------------------------------------------------- read
    async def get_for_manager(self, quote_id: uuid.UUID) -> Quote:
        return await self._require_quote(quote_id)

    async def get_for_client(self, user, quote_id: uuid.UUID) -> Quote:
        """КП своей активной организации; DRAFT и чужое → 404 (без утечки)."""
        await quotes_repo.expire_due(self.db)
        quote = await self._require_quote(quote_id)
        await self._context_for_quote(user, quote)
        if quote.status is QuoteStatus.DRAFT:
            # Черновик менеджера клиент не виден вовсе (этап 8).
            raise QuoteNotFoundError("Коммерческое предложение не найдено")
        return quote

    async def list_for_manager(
        self,
        *,
        status: QuoteStatus | None,
        limit: int,
        after: dict[str, str] | None,
    ) -> list[Quote]:
        await quotes_repo.expire_due(self.db)
        return await quotes_repo.fetch_quotes(
            self.db,
            organization_id=None,
            status=status,
            limit=limit,
            after=after,
        )

    async def list_for_client(
        self,
        user,
        *,
        status: QuoteStatus | None,
        limit: int,
        after: dict[str, str] | None,
        context=None,
    ) -> list[Quote]:
        """Лента КП своей активной организации; черновики не видны."""
        await quotes_repo.expire_due(self.db)
        context = context if context is not None else await self.organizations.resolve(user)
        # Соло-клиент без организации КП не получает — пустая страница вместо
        # случайного «всего списка» (org-scope, этап 8).
        if context.organization_id is None:
            return []
        return await quotes_repo.fetch_quotes(
            self.db,
            organization_id=context.organization_id,
            status=status,
            limit=limit,
            after=after,
            include_draft=False,
        )

    # ----------------------------------------------------------------- pdf
    async def render_pdf(self, quote: Quote) -> Quote:
        """Синхронный рендер PDF КП (этап 8, без Celery).

        HTML → weasyprint → S3 ``quotes/quote-{seq}.pdf`` →
        ``FileAsset(type=QUOTE_PDF, visibility=AUTHED)`` →
        ``pdf_status=READY`` + ``pdf_file_asset_id``. Повторный вызов
        перерендеривает и подменяет asset (старый остаётся в архиве file_assets,
        как и пере-рендер счёта). Ошибка → ``FAILED`` + исключение наружу
        (роутер мапит StorageError в 502).
        """
        if quote.seq is None or quote.number is None:
            # PDF-ключ строится по seq, номер появляется при SEND.
            raise QuoteNotSentError(
                "PDF доступен только для отправленного КП (номер ещё не присвоен)"
            )
        organization = await organizations_repo.get_organization(
            self.db, organization_id=quote.organization_id
        )
        items = list(quote.items)
        # CPU-bound рендер (weasyprint) — в отдельном потоке, чтобы не
        # блокировать event loop (паттерн tasks/export_invoice_pdf.py);
        # AsyncSession остаётся на event loop'е — сессия не threadsafe.
        body = await asyncio.to_thread(
            _render_quote_pdf_bytes, quote=quote, items=items, organization=organization
        )
        key = f"quotes/quote-{quote.seq}.pdf"
        try:
            await asyncio.to_thread(
                storage.upload_fileobj,
                settings.s3_bucket_pdfs,
                key,
                io.BytesIO(body),
                content_type="application/pdf",
            )
        except Exception:
            # Рендер/загрузка упали — фиксируем FAILED (UI покажет кнопку
            # повторного рендера), исключение уходит роутеру.
            quote.pdf_status = QuotePdfStatus.FAILED
            await self.db.flush()
            raise
        asset = quote_pdf_asset(quote=quote, s3_key=key, size_bytes=len(body))
        self.db.add(asset)
        await self.db.flush()
        quote.pdf_status = QuotePdfStatus.READY
        quote.pdf_file_asset_id = asset.id
        await self.db.flush()
        log.info(
            "quote_pdf.done",
            quote=str(quote.id),
            number=quote.number,
            key=key,
            size_bytes=len(body),
        )
        return quote

    # ------------------------------------------------------------- helpers
    async def _require_quote(self, quote_id: uuid.UUID) -> Quote:
        quote = await quotes_repo.get_quote(self.db, quote_id=quote_id)
        if quote is None:
            raise QuoteNotFoundError("Коммерческое предложение не найдено")
        return quote

    async def _context_for_quote(self, user, quote: Quote):
        """Org-scope чтения/accept/reject: КП видно только из активной
        организации, которой оно адресовано (чужое — 404, без утечки)."""
        context = await self.organizations.resolve(user)
        if (
            context.organization_id is None
            or context.organization_id != quote.organization_id
        ):
            raise QuoteNotFoundError("Коммерческое предложение не найдено")
        return context

    async def _validated_items(self, items_payload) -> list[QuoteItem]:
        """Валидация позиций DRAFT (create/edit): товары активны, qty>=1,
        цена > 0, дубли product_id запрещены (схема), 1..500 позиций."""
        if not items_payload or not (1 <= len(items_payload) <= QUOTE_MAX_ITEMS):
            raise QuoteError(
                f"КП должно содержать от 1 до {QUOTE_MAX_ITEMS} позиций"
            )
        product_ids = [item.product_id for item in items_payload]
        products = await catalog_repo.get_by_ids_for_update(self.db, product_ids)
        quote_items: list[QuoteItem] = []
        seen: set[uuid.UUID] = set()
        for item in items_payload:
            if item.product_id in seen:
                raise QuoteError("Дубли позиций по одному товару запрещены")
            seen.add(item.product_id)
            product = products.get(item.product_id)
            if product is None:
                raise QuoteItemUnavailableError(
                    f"Товар {item.product_id} не найден или удалён"
                )
            if product.stock_status is StockStatus.ARCHIVED:
                raise ProductUnavailableError(
                    f"Товар {product.sku} архивный — нельзя включить в КП"
                )
            unit_price = quantize_money(item.unit_price.amount)
            if unit_price <= 0:
                raise QuoteError("Цена позиции КП должна быть больше нуля")
            quote_items.append(
                QuoteItem(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    qty=int(item.quantity),
                    unit_price=unit_price,
                    comment=item.comment,
                )
            )
        return quote_items


__all__ = [
    "IdempotencyInProgressError",
    "IdempotencyKeyReusedError",
    "OrganizationNotFoundError",
    "ProductUnavailableError",
    "QUOTE_ACCEPT_ENDPOINT",
    "QUOTE_MAX_ITEMS",
    "QUOTE_NUMBER_TEMPLATE",
    "QuoteError",
    "QuoteExpiredError",
    "QuoteItemUnavailableError",
    "QuoteNotDraftError",
    "QuoteNotFoundError",
    "QuoteNotSentError",
    "QuotePdfStatus",
    "QuoteService",
    "QuoteStateChangedError",
    "QuoteValidUntilInPastError",
    "QuoteValidUntilRequiredError",
    "StaleResourceVersionError",
    "format_quote_number",
    "quote_accept_fingerprint",
    "quote_pdf_asset",
]
