/**
 * Контракт API v2 «Скидки за объём» (§6, §16 п.41).
 *
 * Лестница «от N шт — X%» живёт на бренде, а не на товаре: ступень одна для
 * всех позиций бренда, а применяется к количеству **строки** заказа. Поэтому
 * в каталоге товар публикует лестницу целиком (`volumeTiers[]`, количество
 * строки там неизвестно), а корзина и заказ — уже выбранную ступень
 * (`volumeTier`).
 *
 * Проценты приходят числом: бэк сериализует Decimal как float, а каталог
 * отдаёт их же в `volumeTiers`. `If-Match` — по `version` **ступени**, а не
 * бренда (§16 п.41 п.8), и бэк не ставит ETag-заголовок, поэтому версию
 * берём из тела ответа.
 */
import { z } from 'zod'

import { uuidSchema } from './common.schema'
import { responseMetaSchema } from './session.schema'

/** Ступень в том виде, в каком её видит каталог: подсказка, а не применённая цена. */
export const volumeTierHintSchema = z
  .object({
    minQty: z.number().int().min(1),
    discountPercent: z.number().gt(0).lt(100),
  })
  .strict()

/** Ступень, применённая к строке корзины (§16 п.41 п.2). */
export const cartLineVolumeTierSchema = z
  .object({
    minQty: z.number().int().min(1),
    discountPercent: z.number().gt(0).lt(100),
  })
  .strict()

export const volumeTierSchema = z
  .object({
    id: uuidSchema,
    brandId: uuidSchema,
    minQty: z.number().int().min(1),
    discountPercent: z.number().gt(0).lt(100),
    version: z.number().int().min(1),
    createdAt: z.string().datetime({ offset: true }),
    updatedAt: z.string().datetime({ offset: true }),
  })
  .strict()

export const volumeTierListResponseSchema = z
  .object({
    data: z.array(volumeTierSchema),
    meta: responseMetaSchema,
  })
  .strict()

export const volumeTierResponseSchema = z
  .object({
    data: volumeTierSchema,
    meta: responseMetaSchema,
  })
  .strict()

/** DELETE отдаёт 204 без тела — тело может прийти пустым или null. */
export const volumeTierDeleteResponseSchema = z.union([z.null(), z.undefined()])

export const volumeTierCreateInputSchema = z
  .object({
    minQty: z.number().int().min(1),
    discountPercent: z.number().gt(0).lt(100),
  })
  .strict()

export const volumeTierUpdateInputSchema = z
  .object({
    minQty: z.number().int().min(1).optional(),
    discountPercent: z.number().gt(0).lt(100).optional(),
  })
  .strict()

export type VolumeTierHint = z.infer<typeof volumeTierHintSchema>
export type CartLineVolumeTier = z.infer<typeof cartLineVolumeTierSchema>
export type VolumeTier = z.infer<typeof volumeTierSchema>
export type VolumeTierCreateInput = z.infer<typeof volumeTierCreateInputSchema>
export type VolumeTierUpdateInput = z.infer<typeof volumeTierUpdateInputSchema>

/**
 * Ближайшая достижимая ступень для количества строки.
 *
 * Дублирует `pick_tier` бэкенда (§16 п.41 п.3): ступени не складываются,
 * берётся одна — с наибольшим порогом, не превышающим количество. Лестница
 * приходит с сервера отсортированной, но сортировку не полагаемся на.
 */
export function pickVolumeTier<T extends { minQty: number }>(
  ladder: readonly T[],
  quantity: number,
): T | null {
  if (!Number.isFinite(quantity) || quantity < 1) return null
  const sorted = [...ladder].sort((a, b) => a.minQty - b.minQty)
  let chosen: T | null = null
  for (const tier of sorted) {
    if (tier.minQty <= quantity) chosen = tier
    else break
  }
  return chosen
}

/** Бейдж «от N шт −X%» для самой нижней ступени — самой «доступной» для клиента. */
export function firstVolumeTierHint(
  ladder: readonly VolumeTierHint[],
): VolumeTierHint | null {
  if (!ladder.length) return null
  return [...ladder].sort((a, b) => a.minQty - b.minQty)[0] ?? null
}
