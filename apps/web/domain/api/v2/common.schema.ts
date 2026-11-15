import { z } from 'zod'

export const uuidSchema = z.string().uuid()
export const currencySchema = z.enum(['BYN', 'EUR', 'RUB', 'USD'])
export const maxDatabaseInteger = 2_147_483_647

export const quantitySchema = z
  .string()
  .regex(/^[1-9]\d*$/, 'Quantity must be a canonical positive decimal string')
  .refine((value) => Number(value) <= maxDatabaseInteger, {
    message: 'Quantity exceeds the database integer range',
  })

export const moneySchema = z
  .object({
    amount: z.string().regex(/^-?\d+\.\d{2}$/),
    currency: currencySchema,
  })
  .strict()

export const rateSchema = z
  .object({
    value: z.string().regex(/^-?\d+\.\d{4}$/),
    // scale — делитель валюты (§17.4): BYN за `scale` единиц валюты, у RUB
    // scale=100. Верхняя граница — 1000, а не 8: реальный масштаб рубля
    // не влезал в прежний предел, и ответ API не проходил валидацию.
    scale: z.number().int().min(0).max(1000),
    source: z.string().min(1).max(64),
  })
  .strict()

export const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
export const dateTimeSchema = z.string().datetime({ offset: true })

export type Money = z.infer<typeof moneySchema>
export type Rate = z.infer<typeof rateSchema>
