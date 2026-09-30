import type { ApiV2Client } from '../api/v2/client'
import { uuidSchema } from '../api/v2/common.schema'
import {
  invoiceResponseSchema,
  invoiceStatusPatchSchema,
  organizationRequisitesPatchSchema,
  type Invoice,
  type InvoiceStatus,
  type OrganizationRequisitesPatch,
} from '../api/v2/invoice.schema'
import {
  organizationDetailResponseSchema,
  type OrganizationDetail,
} from '../api/v2/organizations.schema'

/**
 * Счёт на оплату 1:1 с заказом (§6 «Счета на оплату», §16 п.40).
 *
 * JSON-операции идут через ApiV2Client; PDF отдаётся **байтами** и в JSON
 * клиент не вписывается — транспорт для байтов и сохранение файла внедряются
 * (composables/useInvoiceDownload.ts), здесь остаётся только оркестровка.
 */
export type InvoicePdfFetcher = (path: string) => Promise<Blob>
export type InvoicePdfSaver = (blob: Blob, fileName: string) => void

export interface InvoicePdfTransport {
  fetch: InvoicePdfFetcher
  save: InvoicePdfSaver
}

export interface InvoiceRepository {
  /** Выставить счёт по заказу. 1:1 — повтор отдаёт тот же счёт (тот же ключ). */
  issueForOrder(orderId: string, idempotencyKey: string): Promise<Invoice>
  /** Счёт по заказу. Нет счёта → `AppProblem` 404 `INVOICE_NOT_FOUND`. */
  getByOrder(orderId: string): Promise<Invoice>
  /** Смена статуса счёта; `ifMatch` — версия СЧЁТА, не заказа (§16 п.40 п.8). */
  changeStatus(
    invoiceId: string,
    status: InvoiceStatus,
    ifMatch: string | number,
  ): Promise<Invoice>
  /** Перерендер PDF после FAILED или правки реквизитов. `PENDING` → 409. */
  regeneratePdf(invoiceId: string): Promise<Invoice>
  /** Скачать PDF байтами (никогда presigned — §16 п.37). */
  downloadPdf(invoiceId: string, fileName: string): Promise<void>
  /** Реквизиты организации для счёта; `ifMatch` — версия организации. */
  updateOrganizationRequisites(
    organizationId: string,
    payload: OrganizationRequisitesPatch,
    ifMatch: string | number,
  ): Promise<OrganizationDetail>
}

/**
 * `If-Match` на транспорте — ETag в кавычках (`"3"`), как его ждёт
 * `parse_if_match` на бэке (§6). Числовая версия приводится к этой форме,
 * чтобы вызывающая сторона не собирала заголовок руками.
 */
export function toIfMatch(ifMatch: string | number): string {
  const value = typeof ifMatch === 'number' ? String(ifMatch) : ifMatch.trim()
  if (value.startsWith('"') || value.startsWith('W/')) return value
  return `"${value}"`
}

export function createInvoiceRepository(
  client: ApiV2Client,
  pdf: InvoicePdfTransport,
): InvoiceRepository {
  async function invoice(
    path: string,
    options: Parameters<ApiV2Client['execute']>[2],
  ): Promise<Invoice> {
    const response = await client.execute(path, invoiceResponseSchema, options)
    return response.data.data
  }

  return {
    async issueForOrder(orderId, idempotencyKey) {
      return invoice(`/api/v2/manager/orders/${uuidSchema.parse(orderId)}/invoice`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
      })
    },
    async getByOrder(orderId) {
      return invoice(`/api/v2/orders/${uuidSchema.parse(orderId)}/invoice`, {
        method: 'GET',
      })
    },
    async changeStatus(invoiceId, status, ifMatch) {
      return invoice(`/api/v2/manager/invoices/${uuidSchema.parse(invoiceId)}`, {
        method: 'PATCH',
        // Тело валидируется до отправки: мусор не уходит в сеть.
        body: invoiceStatusPatchSchema.parse({ status }),
        headers: { 'If-Match': toIfMatch(ifMatch) },
      })
    },
    async regeneratePdf(invoiceId) {
      return invoice(`/api/v2/manager/invoices/${uuidSchema.parse(invoiceId)}/pdf`, {
        method: 'POST',
      })
    },
    async downloadPdf(invoiceId, fileName) {
      const blob = await pdf.fetch(
        `/api/v2/orders/invoices/${uuidSchema.parse(invoiceId)}/download`,
      )
      pdf.save(blob, fileName)
    },
    async updateOrganizationRequisites(organizationId, payload, ifMatch) {
      const response = await client.execute(
        `/api/v2/manager/organizations/${uuidSchema.parse(organizationId)}`,
        organizationDetailResponseSchema,
        {
          method: 'PATCH',
          body: organizationRequisitesPatchSchema.parse(payload),
          headers: { 'If-Match': toIfMatch(ifMatch) },
        },
      )
      return response.data.data
    },
  }
}
