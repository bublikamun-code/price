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
export type CatalogProduct = z.infer<typeof catalogProductSchema>
export type CatalogProductResponse = z.infer<typeof catalogProductResponseSchema>
export type CatalogProductsResponse = z.infer<typeof catalogProductsResponseSchema>
export type CatalogFacets = z.infer<typeof catalogFacetsSchema>
export type CatalogFacetsResponse = z.infer<typeof catalogFacetsResponseSchema>
