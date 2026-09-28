import { z } from 'zod'
import { moneySchema, rateSchema, uuidSchema } from './common.schema'

export const catalogProductIdSchema = uuidSchema
export const catalogProductSkuSchema = z.string().min(1).max(128)

export const catalogStockStatusSchema = z.enum(['IN_STOCK', 'PREORDER'])
export const catalogSortSchema = z.enum(['name', '-name', 'price', '-price', 'sku'])
export const catalogPriceCalcModeSchema = z.enum(['fixed', 'nbrb_current'])

export const catalogListQuerySchema = z
  .object({
    q: z.string().optional(),
    brands: z.array(uuidSchema).optional(),
    series: z.array(uuidSchema).optional(),
    stock: catalogStockStatusSchema.optional(),
    model: z.string().optional(),
    sort: catalogSortSchema.optional(),
    limit: z.number().int().min(1).max(100).optional(),
    cursor: z.string().min(1).optional(),
    priceCalcMode: catalogPriceCalcModeSchema.optional(),
  })
  .strict()

const catalogResponseMetaSchema = z
  .object({
    requestId: z.string().min(1),
  })
  .strict()

const catalogCursorMetaSchema = catalogResponseMetaSchema
  .extend({
    nextCursor: z.string().nullable(),
    hasMore: z.boolean(),
    limit: z.number().int().min(1).max(100),
    sort: catalogSortSchema,
  })
  .strict()

export const catalogBrandRefSchema = z
  .object({
    id: uuidSchema,
    name: z.string().min(1).max(255),
  })
  .strict()

export const catalogSeriesRefSchema = z
  .object({
    id: uuidSchema,
    name: z.string().min(1).max(255),
    brandId: uuidSchema,
  })
  .strict()

/**
 * Изображение каталога (§16 п.37, docs/NATIVE_API_CONTRACT.md §6.1).
 * `url` — стабильный v2-путь `/api/v2/media/{id}`, а не presigned-S3: тот
 * протухает за 5 минут и в качестве ключа кэша каждый раз создавал бы новую
 * запись. Внутренние S3-ключи наружу не отдаются, поэтому `photoKey` в
 * контракте нет и не появится.
 */
export const catalogMediaResourceSchema = z
  .object({
    id: uuidSchema,
    url: z.string().min(1),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    mimeType: z.string().min(1),
  })
  .strict()

export const catalogProductSchema = z
  .object({
    id: catalogProductIdSchema,
    sku: catalogProductSkuSchema,
    name: z.string().min(1).max(512),
    brand: catalogBrandRefSchema.nullable(),
    series: catalogSeriesRefSchema.nullable(),
    stockStatus: catalogStockStatusSchema,
    stockQuantity: z.number().int().nullable(),
    attributes: z.record(z.unknown()),
    basePrice: moneySchema,
    retailPrice: moneySchema,
    clientPrice: moneySchema,
    exchangeRate: rateSchema,
    hasDiscount: z.boolean(),
    // Репрезентативный кадр для плитки каталога; полная галерея — в `media`.
    // Оба поля опциональны на клиенте: ответы v1 и старые выкладки v2 фото
    // не несут, и это штатное состояние, а не ошибка контракта.
    // ВНИМАНИЕ: несмотря на имя, сейчас это large-кадр (1200×1200), а не
    // миниатюра — сервер отдаёт photo_key из БД, где лежит только large-ключ
    // (docs/NATIVE_API_CONTRACT.md §6.1). Рендерить надо по фактическим
    // width/height, а не подгонять под 400×400.
    thumbnail: catalogMediaResourceSchema.nullable().optional(),
    media: z.array(catalogMediaResourceSchema).optional(),
  })
  .strict()

export const catalogProductResponseSchema = z
  .object({
    data: catalogProductSchema,
    meta: catalogResponseMetaSchema,
  })
  .strict()

export const catalogProductsResponseSchema = z
  .object({
    data: z.array(catalogProductSchema),
    meta: catalogCursorMetaSchema,
  })
  .strict()

export const catalogFacetsSchema = z
  .object({
    brands: z.array(catalogBrandRefSchema),
    series: z.array(catalogSeriesRefSchema),
    stockStatuses: z.array(catalogStockStatusSchema),
    models: z.array(z.string()),
  })
  .strict()

export const catalogFacetsResponseSchema = z
  .object({
    data: catalogFacetsSchema,
    meta: catalogResponseMetaSchema,
  })
  .strict()

export type CatalogProductId = z.infer<typeof catalogProductIdSchema>
export type CatalogProductSku = z.infer<typeof catalogProductSkuSchema>
export type CatalogStockStatus = z.infer<typeof catalogStockStatusSchema>
export type CatalogSort = z.infer<typeof catalogSortSchema>
export type CatalogPriceCalcMode = z.infer<typeof catalogPriceCalcModeSchema>
export type CatalogListQuery = z.infer<typeof catalogListQuerySchema>
export type CatalogBrandRef = z.infer<typeof catalogBrandRefSchema>
export type CatalogSeriesRef = z.infer<typeof catalogSeriesRefSchema>
export type CatalogMediaResource = z.infer<typeof catalogMediaResourceSchema>
export type CatalogProduct = z.infer<typeof catalogProductSchema>
export type CatalogProductResponse = z.infer<typeof catalogProductResponseSchema>
export type CatalogProductsResponse = z.infer<typeof catalogProductsResponseSchema>
export type CatalogFacets = z.infer<typeof catalogFacetsSchema>
export type CatalogFacetsResponse = z.infer<typeof catalogFacetsResponseSchema>
