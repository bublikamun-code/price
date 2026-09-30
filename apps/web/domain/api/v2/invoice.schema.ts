import { z } from 'zod'
import { dateSchema, dateTimeSchema, moneySchema, uuidSchema } from './common.schema'
import { responseMetaSchema } from './session.schema'

/**
 * Счёт на оплату 1:1 с заказом (§6 «Счета на оплату», §16 п.40,
 * docs/API_V2_CONTRACT.md §12 «Invoices»). Форма `InvoiceOut` зафиксирована
 * каноном: `id`, `orderId`, `number`, `status`, `pdfStatus`, `total` (Money),
 * `issuedAt`, `dueAt?`, `version`, `buyer`/`seller`. Money переиспользуется из
 * common.schema — суммы на границе остаются decimal string.
 */
export const invoiceStatusSchema = z.enum(['ISSUED', 'PAID', 'CANCELLED'])

export const invoicePdfStatusSchema = z.enum(['PENDING', 'READY', 'FAILED'])

/** Банковские реквизиты стороны счёта; незаполненные — прочерк в PDF. */
export const invoicePartyBankSchema = z
  .object({
    name: z.string().max(255).nullable(),
    code: z.string().max(64).nullable(),
    account: z.string().max(64).nullable(),
  })
  .strict()

/**
 * Реквизиты покупателя/продавца — проекция, не замороженная копия: покупатель
 * берётся из `organizations`, продавец — из конфигурации `seller_*` (§10).
 * Ключи приходят всегда (nullable), в том числе когда организации нет.
 */
export const invoicePartySchema = z
  .object({
    legalName: z.string().min(1).max(255),
    taxId: z.string().min(1).max(64).nullable(),
    legalAddress: z.string().min(1).max(2000).nullable(),
    bank: invoicePartyBankSchema.nullable(),
  })
  .strict()

/** Сокращённый блок для коллекции заказов — без сумм и реквизитов (§6). */
export const invoiceSummarySchema = z
  .object({
    id: uuidSchema,
    number: z.string().min(1).max(32),
    status: invoiceStatusSchema,
  })
  .strict()

export const invoiceSchema = z
  .object({
    id: uuidSchema,
    orderId: uuidSchema,
    number: z.string().min(1).max(32),
    status: invoiceStatusSchema,
    pdfStatus: invoicePdfStatusSchema,
    total: moneySchema,
    issuedAt: dateTimeSchema,
    dueAt: dateSchema.nullable(),
    version: z.number().int().min(1),
    buyer: invoicePartySchema,
    seller: invoicePartySchema,
  })
  .strict()

export const invoiceResponseSchema = z
  .object({
    data: invoiceSchema,
    meta: responseMetaSchema,
  })
  .strict()

/** Тело `PATCH /manager/invoices/{id}` — только статус (§6). */
export const invoiceStatusPatchSchema = z
  .object({
    status: invoiceStatusSchema,
  })
  .strict()

/**
 * Тело `PATCH /manager/organizations/{id}` — печатные реквизиты для счёта
 * (§16 п.40 п.4). Все поля nullable: организация может существовать без
 * реквизитов, счёт тогда печатается с прочерками. `version` — необязательная
 * тело-версия для доп. сверки с `If-Match`.
 */
export const organizationRequisitesPatchSchema = z
  .object({
    taxId: z.string().max(64).nullish(),
    legalAddress: z.string().max(2000).nullish(),
    legalPhone: z.string().max(50).nullish(),
    legalEmail: z.string().max(320).nullish(),
    bankName: z.string().max(255).nullish(),
    bankCode: z.string().max(64).nullish(),
    bankAccount: z.string().max(64).nullish(),
    version: z.number().int().min(1).nullish(),
  })
  .strict()

export type InvoiceStatus = z.infer<typeof invoiceStatusSchema>
export type InvoicePdfStatus = z.infer<typeof invoicePdfStatusSchema>
export type InvoicePartyBank = z.infer<typeof invoicePartyBankSchema>
export type InvoiceParty = z.infer<typeof invoicePartySchema>
export type InvoiceSummary = z.infer<typeof invoiceSummarySchema>
export type Invoice = z.infer<typeof invoiceSchema>
export type InvoiceResponse = z.infer<typeof invoiceResponseSchema>
export type InvoiceStatusPatch = z.infer<typeof invoiceStatusPatchSchema>
export type OrganizationRequisitesPatch = z.infer<typeof organizationRequisitesPatchSchema>
