import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import { createApiV2Client, type ApiRequester } from '../domain/api/v2/client'
import { cartLineSchema } from '../domain/api/v2/cart.schema'
import { catalogProductSchema } from '../domain/api/v2/catalog.schema'
import {
  cartLineVolumeTierSchema,
  firstVolumeTierHint,
  pickVolumeTier,
  volumeTierCreateInputSchema,
  volumeTierSchema,
  volumeTierUpdateInputSchema,
} from '../domain/api/v2/volume_tiers.schema'
import { createVolumeTiersRepository } from '../domain/volume_tiers/volume_tiers.repository'

// Контракт скидок за объём (§6, §16 п.41, docs/API_V2_CONTRACT.md §8).
// Стражится: лестница в каталоге (целиком, цена без объёма), применённая
// ступень в корзине (null = не достигнута), одна ступень из нескольких, тип
// процента и If-Match по версии САМОЙ ступени.

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
/** Общие фикстуры API v2 лежат у бэкенда — тем же путём читают их и его тесты. */
const apiFixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8'))

const brandId = '33333333-3333-4333-8333-333333333333'
const tierId = '99999999-1111-4111-8111-111111111111'

function requestSequence(responses: Array<{ body?: unknown; error?: unknown }>) {
  const requests: Array<{ url: string; options: FetchOptions }> = []
  const queue = [...responses]
  const requester: ApiRequester = async <T>(url: string, options: FetchOptions = {}) => {
    requests.push({ url, options })
    const current = queue.shift()
    if (!current) throw new Error('No response configured')
    if ('error' in current) throw current.error
    return current.body as T
  }
  return { requester, requests }
}

function headersOf(options: FetchOptions): Record<string, string> {
  return (options.headers ?? {}) as Record<string, string>
}

function tierBody(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      id: tierId,
      brandId,
      minQty: 10,
      discountPercent: 2.0,
      version: 1,
      createdAt: '2026-09-30T08:15:00Z',
      updatedAt: '2026-09-30T08:15:00Z',
      ...overrides,
    },
    meta: { requestId: 'v2-fixture-volume-tiers-001' },
  }
}

function problemResponse(status: number, code: string, title: string, detail: string): unknown {
  return {
    status,
    data: {
      type: 'about:blank',
      title,
      status,
      detail,
      instance: '/api/v2/problem',
      code,
      requestId: `req-${status}`,
      errors: [],
    },
  }
}

describe('volume tier schema contract', () => {
  it('parses the shared ladder fixture with a numeric percent', () => {
    const parsed = volumeTierSchema.parse(tierBody().data)

    expect(parsed).toMatchObject({
      id: tierId,
      brandId,
      minQty: 10,
      discountPercent: 2.0,
      version: 1,
    })
  })

  it('rejects a percent that arrives as a decimal string', () => {
    // Деньги §6 требует отдавать строкой, процент — нет: один тип поля во всех
    // формах, иначе клиент разбирал бы «2.00» вручную в зависимости от ручки.
    const payload = tierBody({ discountPercent: '2.00' })
    expect(volumeTierSchema.safeParse(payload.data).success).toBe(false)
  })

  it('rejects the 0% and 100% bounds before the request leaves the client', () => {
    expect(volumeTierCreateInputSchema.safeParse({ minQty: 10, discountPercent: 0 }).success).toBe(false)
    expect(volumeTierCreateInputSchema.safeParse({ minQty: 10, discountPercent: 100 }).success).toBe(false)
    expect(volumeTierCreateInputSchema.safeParse({ minQty: 0, discountPercent: 5 }).success).toBe(false)
    expect(volumeTierCreateInputSchema.safeParse({ minQty: 10, discountPercent: 5 }).success).toBe(true)
    // PATCH: хотя бы одно поле, лишние — ошибка, а не «тихое» отсечение.
    expect(volumeTierUpdateInputSchema.safeParse({ discountPercent: 7.5 }).success).toBe(true)
    expect(volumeTierUpdateInputSchema.safeParse({}).success).toBe(true)
    expect(volumeTierUpdateInputSchema.safeParse({ minQty: 10, extra: 1 }).success).toBe(false)
  })

  it('carries the ladder in the catalog without discounting its price', () => {
    const product = catalogProductSchema.parse(apiFixture('catalog_product_detail.json').data)

    expect(product.volumeTiers).toEqual([
      { minQty: 10, discountPercent: 2.0 },
      { minQty: 50, discountPercent: 5.0 },
    ])
    // Каталог не знает количества строки, поэтому clientPrice — без объёма.
    expect(product.clientPrice.amount).toBe('90.00')
  })

  it('carries the reached step in the cart line, already priced in', () => {
    const item = apiFixture('cart_get_success.json').data.items[0]
    const line = cartLineSchema.parse(item)

    expect(line.volumeTier).toEqual({ minQty: 2, discountPercent: 5.0 })
    // Цена строки посчитана со ступенью: 2 шт × 19.00 = 38.00.
    expect(line.unitPrice.amount).toBe('19.00')
    expect(line.lineTotal.amount).toBe('38.00')
  })

  it('accepts a null step for a brand without a ladder', () => {
    const item = apiFixture('cart_repeat_success.json').data.items[0]
    const line = cartLineSchema.parse(item)

    expect(line.volumeTier).toBeNull()
    expect(line.unitPrice.amount).toBe('10.00')
  })

  it('rejects a step carrying a key the contract does not define', () => {
    expect(
      cartLineVolumeTierSchema.safeParse({ minQty: 10, discountPercent: 2, applied: true }).success,
    ).toBe(false)
  })
})

describe('pickVolumeTier', () => {
  const ladder = [
    { minQty: 10, discountPercent: 2.0 },
    { minQty: 50, discountPercent: 5.0 },
    { minQty: 100, discountPercent: 9.0 },
  ]

  it('picks the highest reached step, never a sum of the ones below', () => {
    // «от 10 −2%, от 50 −5%» на 120 шт даёт −9%, а не −16% (§16 п.41 п.3).
    expect(pickVolumeTier(ladder, 120)).toEqual({ minQty: 100, discountPercent: 9.0 })
    expect(pickVolumeTier(ladder, 100)).toEqual({ minQty: 100, discountPercent: 9.0 })
  })

  it('picks the boundary itself, and one step below it', () => {
    expect(pickVolumeTier(ladder, 50)).toEqual({ minQty: 50, discountPercent: 5.0 })
    expect(pickVolumeTier(ladder, 49)).toEqual({ minQty: 10, discountPercent: 2.0 })
  })

  it('returns null below the first threshold and on an empty ladder', () => {
    expect(pickVolumeTier(ladder, 9)).toBeNull()
    expect(pickVolumeTier([], 500)).toBeNull()
  })

  it('sorts an unsorted ladder before choosing', () => {
    const shuffled = [ladder[2]!, ladder[0]!, ladder[1]!]
    expect(pickVolumeTier(shuffled, 60)).toEqual({ minQty: 50, discountPercent: 5.0 })
  })

  it('rejects a non-positive or non-finite quantity instead of returning a step', () => {
    expect(pickVolumeTier(ladder, 0)).toBeNull()
    expect(pickVolumeTier(ladder, -5)).toBeNull()
    expect(pickVolumeTier(ladder, Number.NaN)).toBeNull()
  })
})

describe('firstVolumeTierHint', () => {
  it('points the catalog at the most reachable step', () => {
    const ladder = apiFixture('catalog_product_detail.json').data.volumeTiers
    expect(firstVolumeTierHint(ladder)).toEqual({ minQty: 10, discountPercent: 2.0 })
  })

  it('returns null when the brand has no ladder at all', () => {
    expect(firstVolumeTierHint([])).toBeNull()
  })
})

describe('volume tiers repository', () => {
  it('reads the ladder of a brand and returns it in ascending order', async () => {
    const { requester, requests } = requestSequence([
      { body: apiFixture('volume_tiers_list.json') },
    ])
    const repository = createVolumeTiersRepository(createApiV2Client(requester))

    const tiers = await repository.list(brandId)

    expect(requests[0]?.url).toBe(`/api/v2/manager/brands/${brandId}/volume-tiers`)
    expect(requests[0]?.options.method).toBe('GET')
    expect(tiers.map((tier) => tier.minQty)).toEqual([10, 50])
  })

  it('sends the new step to the brand collection', async () => {
    const { requester, requests } = requestSequence([{ body: tierBody() }])
    const repository = createVolumeTiersRepository(createApiV2Client(requester))

    const created = await repository.create(brandId, { minQty: 10, discountPercent: 2 })

    expect(requests[0]?.url).toBe(`/api/v2/manager/brands/${brandId}/volume-tiers`)
    expect(requests[0]?.options.method).toBe('POST')
    expect(requests[0]?.options.body).toEqual({ minQty: 10, discountPercent: 2 })
    // POST идёт без If-Match: ступени ещё нет, версии не у кого взять.
    expect(headersOf(requests[0]?.options ?? {})['If-Match']).toBeUndefined()
    expect(created.id).toBe(tierId)
  })

  it("sends If-Match with the step's own version, not the brand's", async () => {
    const { requester, requests } = requestSequence([{ body: tierBody({ version: 2 }) }])
    const repository = createVolumeTiersRepository(createApiV2Client(requester))

    const updated = await repository.update(tierId, 1, { discountPercent: 7.5 })

    expect(requests[0]?.url).toBe(`/api/v2/manager/volume-tiers/${tierId}`)
    expect(requests[0]?.options.method).toBe('PATCH')
    expect(headersOf(requests[0]?.options ?? {})['If-Match']).toBe('"1"')
    expect(requests[0]?.options.body).toEqual({ discountPercent: 7.5 })
    expect(updated.version).toBe(2)
  })

  it('deletes with If-Match and tolerates the empty 204 body', async () => {
    const { requester, requests } = requestSequence([{ body: null }])
    const repository = createVolumeTiersRepository(createApiV2Client(requester))

    await repository.remove(tierId, 4)

    expect(requests[0]?.url).toBe(`/api/v2/manager/volume-tiers/${tierId}`)
    expect(requests[0]?.options.method).toBe('DELETE')
    expect(headersOf(requests[0]?.options ?? {})['If-Match']).toBe('"4"')
  })

  it('keeps a stale step and a duplicate threshold readable as problems', async () => {
    const stale = requestSequence([
      {
        error: problemResponse(
          409,
          'STALE_RESOURCE_VERSION',
          'Ресурс изменился',
          'Версия ступени устарела',
        ),
      },
    ])
    await expect(
      createVolumeTiersRepository(createApiV2Client(stale.requester)).update(tierId, 1, {
        minQty: 20,
      }),
    ).rejects.toMatchObject({ code: 'STALE_RESOURCE_VERSION', status: 409 })

    const duplicate = requestSequence([
      {
        error: problemResponse(
          409,
          'VOLUME_TIER_DUPLICATE_THRESHOLD',
          'Такой порог уже есть',
          'В лестнице бренда уже есть ступень от 10 шт',
        ),
      },
    ])
    await expect(
      createVolumeTiersRepository(createApiV2Client(duplicate.requester)).create(brandId, {
        minQty: 10,
        discountPercent: 3,
      }),
    ).rejects.toMatchObject({ code: 'VOLUME_TIER_DUPLICATE_THRESHOLD', status: 409 })
  })

  it('validates the brand and step ids before opening a request', async () => {
    const { requester, requests } = requestSequence([])
    const repository = createVolumeTiersRepository(createApiV2Client(requester))

    await expect(repository.list('not-a-uuid')).rejects.toThrow()
    await expect(repository.update('nope', 1, { minQty: 5 })).rejects.toThrow()
    expect(requests).toHaveLength(0)
  })
})
