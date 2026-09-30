"""Публичные схемы счёта на оплату. См. ARCHITECTURE_PLAN.md §6 «Счета на оплату», §16 п.40.

Форма ``InvoiceOut`` зафиксирована каноном: ``id``, ``orderId``, ``number``,
``status``, ``pdfStatus``, ``total`` (Money), ``issuedAt``, ``dueAt?``,
``version``, ``buyer``/``seller``. Money переиспользуется из
``schemas.v2.common`` — суммы на публичной границе остаются decimal string.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.config import settings
from app.models.enums import InvoicePdfStatus, InvoiceStatus
from app.models.invoice import Invoice
from app.models.organization import Organization
from app.schemas.v2.common import Money, V2Model, money_amount


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money(value: Decimal | float | str, currency: str) -> Money:
    return Money(amount=money_amount(value), currency=currency)


class InvoicePartyBank(V2Model):
    """Банковские реквизиты стороны счёта; незаполненные — прочерк в PDF."""

    name: str | None
    code: str | None
    account: str | None


class InvoiceParty(V2Model):
    """Реквизиты покупателя/продавца — проекция, не замороженная копия.

    Дублирующий ``organizations.unp`` не вводится: ``tax_id`` уже семантически
    УНП (§16 п.40 п.4).
    """

    legal_name: str
    tax_id: str | None
    legal_address: str | None
    bank: InvoicePartyBank | None


class InvoiceSummary(V2Model):
    """Сокращённый блок для коллекции заказов — без сумм и реквизитов."""

    id: uuid.UUID
    number: str
    status: InvoiceStatus


class InvoiceOut(V2Model):
    """Полная форма счёта (§6). Суммы — decimal string + currency."""

    id: uuid.UUID
    order_id: uuid.UUID
    number: str
    status: InvoiceStatus
    pdf_status: InvoicePdfStatus
    total: Money
    issued_at: datetime
    due_at: date | None
    version: int
    buyer: InvoiceParty
    seller: InvoiceParty


class InvoiceStatusPatch(V2Model):
    """Тело ``PATCH /manager/invoices/{id}`` — только статус."""

    status: InvoiceStatus


class OrganizationBillingPatch(V2Model):
    """Тело ``PATCH /manager/organizations/{id}`` — реквизиты для счёта.

    Отдельная схема от ``organizations.Organization*Patch``: здесь нет
    управления доступом, только печатные реквизиты (§16 п.40 п.4).
    """

    tax_id: str | None = None
    legal_address: str | None = None
    legal_phone: str | None = None
    legal_email: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    bank_account: str | None = None
    # Опциональное тело-версия: клиент может прислать её для доп. сверки,
    # как это делает PATCH membership (§6).
    version: int | None = None


def invoice_summary(invoice: Invoice) -> InvoiceSummary:
    return InvoiceSummary(
        id=invoice.id,
        number=invoice.number,
        status=invoice.status,
    )


def invoice_buyer(organization: Organization | None) -> InvoiceParty:
    """Реквизиты покупателя — из organizations (может отсутствовать)."""
    if organization is None:
        return InvoiceParty(
            legal_name="—",
            tax_id=None,
            legal_address=None,
            bank=None,
        )
    return InvoiceParty(
        legal_name=organization.legal_name,
        tax_id=organization.tax_id,
        legal_address=organization.legal_address,
        bank=InvoicePartyBank(
            name=organization.bank_name,
            code=organization.bank_code,
            account=organization.bank_account,
        ),
    )


def invoice_seller() -> InvoiceParty:
    """Реквизиты продавца — из конфигурации ``seller_*`` (§10), не из БД.

    Отдельный продавец в БД не заводим: это реквизиты нашей организации, они
    меняются деплоем, а не правкой клиентской карточки.
    """
    return InvoiceParty(
        legal_name=settings.seller_legal_name or "—",
        tax_id=settings.seller_tax_id or None,
        legal_address=settings.seller_address or None,
        bank=InvoicePartyBank(
            name=settings.seller_bank_name or None,
            code=settings.seller_bank_code or None,
            account=settings.seller_bank_account or None,
        ),
    )


def invoice_out(
    invoice: Invoice, *, organization: Organization | None
) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id,
        order_id=invoice.order_id,
        number=invoice.number,
        status=invoice.status,
        pdf_status=invoice.pdf_status,
        total=_money(invoice.total_amount, invoice.currency_code),
        issued_at=_utc(invoice.issued_at),
        # due_at — TIMESTAMPTZ в БД, в контракте это «YYYY-MM-DD?» (§6).
        due_at=invoice.due_at.date() if invoice.due_at else None,
        version=invoice.version,
        buyer=invoice_buyer(organization),
        seller=invoice_seller(),
    )


__all__ = [
    "InvoiceOut",
    "InvoiceParty",
    "InvoicePartyBank",
    "InvoiceStatusPatch",
    "InvoiceSummary",
    "OrganizationBillingPatch",
    "invoice_out",
    "invoice_summary",
]
