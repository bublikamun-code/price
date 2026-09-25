import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import {
  cartItemAddSchema,
  cartResponseSchema,
} from '../domain/api/v2/cart.schema'
import {
  ApiContractError,
  createApiV2Client,
  type ApiRequester,
} from '../domain/api/v2/client'
import { AppProblem } from '../domain/api/v2/problem'
import { createCartRepository } from '../domain/cart/cart.repository'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const apiFixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8'))

interface RecordedRequest {
  url: string
  options: FetchOptions
}

function requestSequence(
  responses: Array<{ body?: unknown; etag?: string; error?: unknown }>,
) {
  const requests: RecordedRequest[] = []
  const queue = [...responses]
  const requester: ApiRequester = async <T>(url: string, options: FetchOptions = {}) => {
    requests.push({ url, options })
    const current = queue.shift()
    if (!current) throw new Error('No response configured')
    if (current.error) throw current.error

    const hooks = Array.isArray(options.onResponse)
      ? options.onResponse
      : options.onResponse
        ? [options.onResponse]
        : []
    const response = new Response(null, {
      headers: current.etag ? { etag: current.etag } : undefined,
    })
    for (const hook of hooks) await hook({ response } as never)
    return current.body as T
  }
  return { requester, requests }
}

describe('API v2 cart contract', () => {
  it('validates the shared cart fixture and preserves metadata', () => {
    const parsed = cartResponseSchema.parse(apiFixture('cart_get_success.json'))

    expect(parsed.data.organizationId).toBe('77777777-7777-4777-8777-777777777777')
    expect(parsed.data.totalItems).toBe(1)
    expect(parsed.data.exchangeRate.value).toBe('2.0000')
    expect(parsed.meta.requestId).toBe('v2-fixture-cart-get-001')
  })

  it('rejects legacy and internal-media-shaped payloads', () => {
    const legacy = apiFixture('cart_get_success.json')
    legacy.data.items[0].product_id = legacy.data.items[0].productId
    delete legacy.data.items[0].productId
    expect(cartResponseSchema.safeParse(legacy).success).toBe(false)

    const internalMedia = apiFixture('cart_get_success.json')
    internalMedia.data.items[0].photoKey = 'products/private/photo.jpg'
    expect(cartResponseSchema.safeParse(internalMedia).success).toBe(false)
  })

  it('accepts only canonical positive quantity strings', () => {
    const valid = apiFixture('cart_item_add_request.json')
    expect(cartItemAddSchema.safeParse(valid).success).toBe(true)
    expect(cartItemAddSchema.safeParse({ ...valid, quantity: '02' }).success).toBe(false)
    expect(cartItemAddSchema.safeParse({ ...valid, quantity: 2 }).success).toBe(false)
    expect(
      cartItemAddSchema.safeParse({ ...valid, quantity: '2147483648' }).success,
    ).toBe(false)
  })

  it('keeps the existing get contract while exposing ETag for cart writes', async () => {
    const fixture = apiFixture('cart_get_success.json')
    const { requester } = requestSequence([
      { body: fixture, etag: '"4"' },
      { body: fixture, etag: '"4"' },
    ])
    const client = createApiV2Client(requester)

    const response = await client.get('/api/v2/cart', cartResponseSchema)
    const withMetadata = await client.execute('/api/v2/cart', cartResponseSchema, {
      method: 'GET',
    })

    expect(response.data.version).toBe(4)
    expect(withMetadata.etag).toBe('"4"')
  })

  it('uses UUID writes, If-Match, and the correct methods without organizationId', async () => {
    const fixture = apiFixture('cart_get_success.json')
    const addPayload = apiFixture('cart_item_add_request.json')
    const { requester, requests } = requestSequence([
      { body: fixture, etag: '"4"' },
      { body: fixture, etag: '"5"' },
      { body: fixture, etag: '"6"' },
      { body: fixture, etag: '"7"' },
      { body: fixture, etag: '"8"' },
    ])
    const repository = createCartRepository(createApiV2Client(requester))
    const productId = '66666666-6666-4666-8666-666666666666'

    await repository.getCurrent()
    await repository.addItem(addPayload, '"4"')
    await repository.replaceItem(productId, { quantity: '3', note: null }, '"5"')
    await repository.removeItem(productId, '"6"')
    await repository.clear('"7"')

    expect(requests.map(({ options }) => options.method)).toEqual([
      'GET',
      'POST',
      'PUT',
      'DELETE',
      'DELETE',
    ])
    expect(requests[1]?.options.headers).toMatchObject({ 'If-Match': '"4"' })
    expect(requests[1]?.options.body).toEqual(addPayload)
    expect(JSON.stringify(requests[1]?.options.body)).not.toContain('organizationId')
    expect(requests[2]?.url).toBe(`/api/v2/cart/items/${productId}`)
  })

  it('normalizes stale cart writes to AppProblem', async () => {
    const fixture = apiFixture('problem_stale_cart_version.json')
    const { requester } = requestSequence([{ error: { data: fixture } }])
    const client = createApiV2Client(requester)
    const repository = createCartRepository(client)

    const problem = await repository
      .removeItem('66666666-6666-4666-8666-666666666666', '"1"')
      .then(() => null)
      .catch((cause: unknown) => cause)

    expect(problem).toBeInstanceOf(AppProblem)
    expect(problem).toMatchObject({
      code: 'STALE_RESOURCE_VERSION',
      status: 409,
      requestId: 'v2-fixture-cart-stale-001',
    })
  })

  it('keeps contract failures distinct from server problems', async () => {
    const { requester } = requestSequence([{ body: { data: {}, meta: {} } }])
    const client = createApiV2Client(requester)

    await expect(client.get('/api/v2/cart', cartResponseSchema)).rejects.toBeInstanceOf(
      ApiContractError,
    )
  })
})
