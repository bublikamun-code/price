import { z } from 'zod'
import { maxDatabaseInteger, moneySchema, quantitySchema, rateSchema, uuidSchema } from './common.schema'
import { responseMetaSchema } from './session.schema'
import { cartLineVolumeTierSchema } from './volume_tiers.schema'

const uuid = uuidSchema

export const cartQuantitySchema = quantitySchema

export const cartItemAddSchema = z
  .object({
    productId: uuid,
    quantity: cartQuantitySchema,
    note: z.string().max(2000).nullable().optional(),
  })
  .strict()

export const cartItemReplaceSchema = z
  .object({
    quantity: cartQuantitySchema,
    note: z.string().max(2000).nullable().optional(),
  })
  .strict()

export const cartLineSchema = z
  .object({
    productId: uuid,
    sku: z.string().min(1),
    name: z.string().min(1),
    brandName: z.string().nullable(),
    stockStatus: z.string().min(1),
    quantity: z.number().int().min(1).max(maxDatabaseInteger),
    note: z.string().max(2000).nullable(),
    unitPrice: moneySchema,
    lineTotal: moneySchema,
    // Достигнутая ступень скидки за объём, уже учтённая в unitPrice
    // (§16 п.41 п.2). null, когда количество строки ниже первого порога или
    // лестницы у бренда нет.
    volumeTier: cartLineVolumeTierSchema.nullable().optional(),
  })
  .strict()

export const cartSummarySchema = z
  .object({
    id: uuid,
    organizationId: uuid.nullable(),
    version: z.number().int().min(1),
    items: z.array(cartLineSchema),
    total: moneySchema,
    totalItems: z.number().int().min(0),
    exchangeRate: rateSchema,
  })
  .strict()

export const cartResponseSchema = z
  .object({
    data: cartSummarySchema,
    meta: responseMetaSchema,
  })
  .strict()

export type CartQuantity = z.infer<typeof cartQuantitySchema>
export type CartItemAdd = z.infer<typeof cartItemAddSchema>
export type CartItemReplace = z.infer<typeof cartItemReplaceSchema>
export type CartLine = z.infer<typeof cartLineSchema>
export type CartSummary = z.infer<typeof cartSummarySchema>
export type CartResponse = z.infer<typeof cartResponseSchema>
