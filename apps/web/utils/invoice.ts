// Подписи и вспомогательные функции счёта на оплату (§16 п.40).
// Тон — тот же контракт, что у components/ui/StatusBadge.vue и
// utils/order-status.ts; сами коды статусов живут в домене
// (domain/api/v2/invoice.schema.ts), здесь только представление.
import type { InvoicePdfStatus, InvoiceStatus } from '~/domain/api/v2/invoice.schema'

export type InvoiceTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export const INVOICE_STATUS_META: Record<InvoiceStatus, { label: string; tone: InvoiceTone }> = {
  ISSUED: { label: 'Выставлен', tone: 'info' },
  PAID: { label: 'Оплачен', tone: 'success' },
  CANCELLED: { label: 'Отменён', tone: 'danger' },
}

export const INVOICE_STATUS_ORDER: InvoiceStatus[] = ['ISSUED', 'PAID', 'CANCELLED']

export const INVOICE_PDF_STATUS_META: Record<
  InvoicePdfStatus,
  { label: string; tone: InvoiceTone }
> = {
  PENDING: { label: 'Готовится', tone: 'warning' },
  READY: { label: 'Готов', tone: 'success' },
  FAILED: { label: 'Ошибка рендера', tone: 'danger' },
}

export const INVOICE_STATUS_OPTIONS = INVOICE_STATUS_ORDER.map((status) => ({
  value: status,
  label: INVOICE_STATUS_META[status].label,
}))

/**
 * Имя файла для сохранения PDF. Номер счёта (`СЧ-2026-000042`) содержит
 * кириллицу и валиден для браузера, поэтому резервируем только опасное:
 * путь, разделители, управляющие символы. Точка тоже убирается — иначе
 * «../../etc/passwd» сохранился бы именем с `..` внутри.
 */
export function invoiceFileName(number: string, fallback = 'invoice.pdf'): string {
  const safe = number
    .replace(/[^\p{L}\p{N}_-]+/gu, '_')
    .replace(/^[._-]+/, '')
    .replace(/[._-]+$/, '')
  return safe ? `${safe}.pdf` : fallback
}
