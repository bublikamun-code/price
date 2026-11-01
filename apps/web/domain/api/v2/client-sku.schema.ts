import { z } from 'zod'
import {
  catalogProductIdSchema,
  catalogProductSkuSchema,
} from './catalog.schema'
import { dateTimeSchema, moneySchema, uuidSchema } from './common.schema'

// Кросс-справочник клиентских артикулов (Этап 7, §16 п.43). Клиентские
// эндпоинты /api/v2/me/organization/client-sku-mappings резолвят организацию
// из сессии, менеджерские /api/v2/manager/organizations/{organizationId}/...
// требуют staff. Ответы и тела — camelCase, envelope SuccessResponse — strict:
// { data, meta: { requestId } }; списки пагинируются offset-ом (page/pageSize).
// Поля, которых бэк может не прислать (аннотации товара у UNKNOWN/AMBIGUOUS),
// помечены .nullish() явно — отсутствие ключа штатно, а не ошибка контракта.

/** Клиентский артикул: бэк тримит на транспортной границе, 1..64 символа. */
export const clientSkuInputSchema = z.string().trim().min(1).max(64)

export const clientSkuMappingSchema = z
  .object({
    id: uuidSchema,
    organizationId: uuidSchema,
    clientSku: z.string().min(1).max(64),
    productId: catalogProductIdSchema,
    // Примечание факультативно: бэк хранит null для «без заметки».
    note: z.string().max(500).nullish(),
    version: z.number().int().min(1),
    createdAt: dateTimeSchema,
    updatedAt: dateTimeSchema,
  })
  .strict()

export const clientSkuMappingCreateSchema = z
  .object({
    clientSku: clientSkuInputSchema,
    productId: catalogProductIdSchema,
    note: z.string().max(500).nullish(),
  })
  .strict()

export const clientSkuMappingUpdateSchema = z
  .object({
    productId: catalogProductIdSchema.optional(),
    note: z.string().max(500).nullish(),
  })
  .strict()

export const clientSkuMappingListQuerySchema = z
  .object({
    // Поиск по клиентскому артикулу/примечанию — GET ?query=...
    query: z.string().trim().max(128).optional(),
    page: z.number().int().min(1).optional(),
    pageSize: z.number().int().min(1).max(100).optional(),
  })
  .strict()

// DELETE отдаёт 204 без тела; ofetch для пустого ответа даёт undefined/''
// (см. documentDeleteResponseSchema).
export const clientSkuMappingDeleteResponseSchema = z.union([
  z.null(),
  z.undefined(),
  z.literal(''),
])

const clientSkuResponseMetaSchema = z
  .object({
    requestId: z.string().min(1),
  })
  .strict()

export const clientSkuMappingResponseSchema = z
  .object({
    data: clientSkuMappingSchema,
    meta: clientSkuResponseMetaSchema,
  })
  .strict()

export const clientSkuMappingListResponseSchema = z
  .object({
    data: z.array(clientSkuMappingSchema),
    meta: clientSkuResponseMetaSchema
      .extend({
        page: z.number().int().min(1),
        pageSize: z.number().int().min(1),
        total: z.number().int().min(0),
      })
      .strict(),
  })
  .strict()

// POST /apply-csv — отчёт применения CSV-списка. unitPrice — клиентская цена
// строки как Money {amount, currency}; stockStatus бэк отдаёт строкой
// (значения StockStatus), клиент отображает толерантно.
export const applyCsvRequestSchema = z
  .object({
    csv: z.string().min(1).max(262144),
  })
  .strict()

export const applyCsvRowStatusSchema = z.enum(['MATCHED', 'UNKNOWN', 'AMBIGUOUS'])

export const applyCsvRowSchema = z
  .object({
    clientSku: z.string().min(1).max(64),
    qty: z.number().int().min(1),
    status: applyCsvRowStatusSchema,
    productId: catalogProductIdSchema.nullish(),
    productName: z.string().min(1).max(512).nullish(),
    productSku: catalogProductSkuSchema.nullish(),
    unitPrice: moneySchema.nullish(),
    stockStatus: z.string().max(32).nullish(),
    message: z.string().max(1000).nullish(),
  })
  .strict()

export const applyCsvSummarySchema = z
  .object({
    matched: z.number().int().min(0),
    unknown: z.number().int().min(0),
    ambiguous: z.number().int().min(0),
    cartAdded: z.number().int().min(0),
  })
  .strict()

export const applyCsvResponseSchema = z
  .object({
    data: z
      .object({
        rows: z.array(applyCsvRowSchema),
        summary: applyCsvSummarySchema,
        cartVersion: z.string().min(1).nullable(),
      })
      .strict(),
    meta: clientSkuResponseMetaSchema,
  })
  .strict()

export type ClientSkuMapping = z.infer<typeof clientSkuMappingSchema>
export type ClientSkuMappingCreate = z.infer<typeof clientSkuMappingCreateSchema>
export type ClientSkuMappingUpdate = z.infer<typeof clientSkuMappingUpdateSchema>
export type ClientSkuMappingListQuery = z.infer<typeof clientSkuMappingListQuerySchema>
export type ClientSkuMappingResponse = z.infer<typeof clientSkuMappingResponseSchema>
export type ClientSkuMappingListResponse = z.infer<typeof clientSkuMappingListResponseSchema>
export type ApplyCsvRequest = z.infer<typeof applyCsvRequestSchema>
export type ApplyCsvRowStatus = z.infer<typeof applyCsvRowStatusSchema>
export type ApplyCsvRow = z.infer<typeof applyCsvRowSchema>
export type ApplyCsvSummary = z.infer<typeof applyCsvSummarySchema>
export type ApplyCsvResponse = z.infer<typeof applyCsvResponseSchema>
