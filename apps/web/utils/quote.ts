// Подписи и вспомогательные функции коммерческих предложений (Э8).
// Тон — тот же контракт, что у utils/invoice.ts и utils/order-status.ts;
// сами коды статусов живут в домене (domain/api/v2/quote.schema.ts),
// здесь только представление. Бейджи статусов КП — в нейтральной гамме:
// синий/индиго (info) зарезервирован под активные действия интерфейса.
import type { QuotePdfStatus, QuoteStatus } from '~/domain/api/v2/quote.schema'

export type QuoteTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export const QUOTE_STATUS_META: Record<QuoteStatus, { label: string; tone: QuoteTone }> = {
  DRAFT: { label: 'Черновик', tone: 'neutral' },
  SENT: { label: 'Отправлено', tone: 'warning' },
  ACCEPTED: { label: 'Принято', tone: 'success' },
  REJECTED: { label: 'Отклонено', tone: 'danger' },
  EXPIRED: { label: 'Истекло', tone: 'neutral' },
}

export const QUOTE_STATUS_TABS: Array<{ value: '' | QuoteStatus; label: string }> = [
  { value: '', label: 'Все' },
  { value: 'DRAFT', label: 'Черновики' },
  { value: 'SENT', label: 'Отправленные' },
  { value: 'ACCEPTED', label: 'Принятые' },
  { value: 'REJECTED', label: 'Отклонённые' },
  { value: 'EXPIRED', label: 'Истёкшие' },
]

/** Клиент DRAFT не видит вовсе (org-scope, Э8) — табы без черновиков. */
export const QUOTE_CLIENT_STATUS_TABS: Array<{ value: '' | QuoteStatus; label: string }> = [
  { value: '', label: 'Все' },
  { value: 'SENT', label: 'Отправленные' },
  { value: 'ACCEPTED', label: 'Принятые' },
  { value: 'REJECTED', label: 'Отклонённые' },
  { value: 'EXPIRED', label: 'Истёкшие' },
]

export const QUOTE_PDF_STATUS_META: Record<QuotePdfStatus, { label: string; tone: QuoteTone }> = {
  PENDING: { label: 'Готовится', tone: 'warning' },
  READY: { label: 'Готов', tone: 'success' },
  FAILED: { label: 'Ошибка рендера', tone: 'danger' },
}

/**
 * Имя файла для сохранения PDF КП. Номер (`КП-2026-000001`) содержит
 * кириллицу и валиден для браузера — резервируем только опасное: путь,
 * разделители, управляющие символы (тот же подход, что в invoiceFileName).
 */
export function quoteFileName(number: string | null, fallback = 'quote.pdf'): string {
  if (!number) return fallback
  const safe = number
    .replace(/[^\p{L}\p{N}_-]+/gu, '_')
    .replace(/^[._-]+/, '')
    .replace(/[._-]+$/, '')
  return safe ? `${safe}.pdf` : fallback
}

/**
 * Ввод цены в конструкторе КП → decimal string с двумя знаками
 * ("15,5" → "15.50"). Строка ровно то, что ждёт Money на бэке.
 */
export function normalizePriceInput(input: string): string | null {
  const normalized = input.replace(',', '.').trim()
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(normalized)) return null
  const value = Number(normalized)
  if (!Number.isFinite(value) || value <= 0) return null
  return value.toFixed(2)
}

/**
 * Ввод количества → канонический decimal string ("2" → "2", " 3 " → "3").
 * Quantity на бэке — строка `^[1-9]\d*$`, ноль и мусор не проходят.
 */
export function normalizeQuantityInput(input: string): string | null {
  const normalized = input.trim()
  if (!/^[1-9]\d{0,9}$/.test(normalized)) return null
  return normalized
}
