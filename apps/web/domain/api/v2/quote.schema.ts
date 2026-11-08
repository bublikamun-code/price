import { z } from 'zod'
import { dateTimeSchema, moneySchema, quantitySchema, uuidSchema } from './common.schema'
import { orderDeliveryCreateSchema, orderResponseSchema } from './order.schema'
import { responseMetaSchema } from './session.schema'

/**
 * Коммерческие предложения (Э8, docs/API_V2_CONTRACT.md §«Quotes»). Схемы —
 * 1:1 с `apps/api/app/schemas/v2/quotes.py`: `QuoteOut` (полная форма),
 * `QuoteSummary` (проекция коллекции), `QuoteStatusOut` (результат рендера
 * PDF). Money переиспользуется из common.schema — суммы на границе остаются
 * decimal string, цены КП всегда BYN (заморозка без пересчёта курса, §8).
 */
export const quoteStatusSchema = z.enum(['DRAFT', 'SENT', 'ACCEPTED', 'REJECTED', 'EXPIRED'])

export const quotePdfStatusSchema = z.enum(['PENDING', 'READY', 'FAILED'])

/** Позиция КП: quantity приходит числом, unitPrice/lineTotal — Money. */
export const quoteItemSchema = z
  .object({
    id: uuidSchema,
    productId: uuidSchema,
    sku: z.string().min(1),
    name: z.string().min(1),
    quantity: z.number().int().min(1),
    unitPrice: moneySchema,
    lineTotal: moneySchema,
    comment: z.string().nullable(),
  })
  .strict()

/**
 * Полная форма КП. У DRAFT `number` и `seq` — null (номер присваивается при
 * SEND); `pdfFileAssetId` наружу не отдаётся — только внутри QuoteStatusOut.
 */
export const quoteSchema = z
  .object({
    id: uuidSchema,
    organizationId: uuidSchema,
    number: z.string().min(1).nullable(),
    status: quoteStatusSchema,
    validUntil: dateTimeSchema.nullable(),
    seq: z.number().int().min(1).nullable(),
    total: moneySchema,
    pdfStatus: quotePdfStatusSchema,
    items: z.array(quoteItemSchema),
    version: z.number().int().min(1),
    createdAt: dateTimeSchema,
    updatedAt: dateTimeSchema,
  })
  .strict()

/** Проекция коллекции (CursorResponse[QuoteSummary]): без позиций и PDF. */
export const quoteSummarySchema = z
  .object({
    id: uuidSchema,
    organizationId: uuidSchema,
    number: z.string().min(1).nullable(),
    status: quoteStatusSchema,
    validUntil: dateTimeSchema.nullable(),
    total: moneySchema,
    version: z.number().int().min(1),
    createdAt: dateTimeSchema,
  })
  .strict()

/** Тело `POST /manager/quotes/{quoteId}/pdf` (синхронный рендер). */
export const quotePdfRenderSchema = z
  .object({
    id: uuidSchema,
    pdfStatus: quotePdfStatusSchema,
    pdfFileAssetId: uuidSchema.nullable(),
  })
  .strict()

// ---------------------------------------------------------------- payloads

/**
 * Позиция при создании/правке: quantity — канонический decimal string
 * (`"2"`, как требует Quantity на бэке), цена — Money с фиксированной
 * точкой и валютой BYN.
 */
export const quoteItemCreateSchema = z
  .object({
    productId: uuidSchema,
    quantity: quantitySchema,
    unitPrice: moneySchema,
    comment: z.string().nullable().optional(),
  })
  .strict()

/** Тело `POST /manager/quotes`: адресат + позиции (1..500) + срок действия. */
export const quoteCreateSchema = z
  .object({
    organizationId: uuidSchema,
    items: z.array(quoteItemCreateSchema).min(1).max(500),
    validUntil: dateTimeSchema.nullable().optional(),
  })
  .strict()
  .superRefine((payload, context) => {
    const seen = new Set<string>()
    payload.items.forEach((item, index) => {
      if (seen.has(item.productId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['items', index, 'productId'],
          message: 'Duplicate productId values are not allowed',
        })
      }
      seen.add(item.productId)
    })
  })

/** Тело `PATCH /manager/quotes/{quoteId}` (DRAFT): None — «не трогать». */
export const quoteEditSchema = z
  .object({
    items: z.array(quoteItemCreateSchema).min(1).max(500).nullable().optional(),
    validUntil: dateTimeSchema.nullable().optional(),
  })
  .strict()
  .superRefine((payload, context) => {
    if (!payload.items) return
    const seen = new Set<string>()
    payload.items.forEach((item, index) => {
      if (seen.has(item.productId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['items', index, 'productId'],
          message: 'Duplicate productId values are not allowed',
        })
      }
      seen.add(item.productId)
    })
  })

/** Тело `POST /quotes/{quoteId}/accept` — delivery как у создания заявки v2. */
export const quoteAcceptSchema = z
  .object({
    delivery: orderDeliveryCreateSchema,
  })
  .strict()

// --------------------------------------------------------------- responses

export const quoteResponseSchema = z
  .object({
    data: quoteSchema,
    meta: responseMetaSchema,
  })
  .strict()

export const quotePdfRenderResponseSchema = z
  .object({
    data: quotePdfRenderSchema,
    meta: responseMetaSchema,
  })
  .strict()

export const quoteListQuerySchema = z
  .object({
    status: quoteStatusSchema.optional(),
    limit: z.number().int().min(1).max(100).optional(),
    cursor: z.string().max(4096).optional(),
  })
  .strict()

export const quoteListResponseSchema = z
  .object({
    data: z.array(quoteSummarySchema),
    meta: z
      .object({
        requestId: z.string().min(1),
        nextCursor: z.string().min(1).nullable(),
        hasMore: z.boolean(),
        limit: z.number().int().min(1).max(100),
        sort: z.literal('createdAt,id'),
      })
      .strict(),
  })
  .strict()

/** `POST /quotes/{quoteId}/accept` отдаёт OrderDetail (как создание заявки). */
export const quoteAcceptResponseSchema = orderResponseSchema

// DELETE отдаёт 204 без тела: ofetch возвращает пустую строку или undefined.
export const quoteDeleteResponseSchema = z.union([z.null(), z.undefined(), z.literal('')])

export type QuoteStatus = z.infer<typeof quoteStatusSchema>
export type QuotePdfStatus = z.infer<typeof quotePdfStatusSchema>
export type QuoteItem = z.infer<typeof quoteItemSchema>
export type QuoteOut = z.infer<typeof quoteSchema>
export type QuoteSummary = z.infer<typeof quoteSummarySchema>
export type QuoteResponse = z.infer<typeof quoteResponseSchema>
export type QuotePdfRender = z.infer<typeof quotePdfRenderSchema>
export type QuoteItemCreate = z.infer<typeof quoteItemCreateSchema>
export type QuoteCreate = z.infer<typeof quoteCreateSchema>
export type QuoteEdit = z.infer<typeof quoteEditSchema>
export type QuoteAccept = z.infer<typeof quoteAcceptSchema>
export type QuoteListQuery = z.infer<typeof quoteListQuerySchema>
export type QuoteListResponse = z.infer<typeof quoteListResponseSchema>
export type QuoteAcceptResponse = z.infer<typeof quoteAcceptResponseSchema>
