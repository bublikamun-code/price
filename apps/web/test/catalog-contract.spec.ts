import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import { ApiContractError, createApiV2Client, type ApiRequester } from '../domain/api/v2/client'
import {
  catalogFacetsResponseSchema,
  catalogProductsResponseSchema,
} from '../domain/api/v2/catalog.schema'
import {
  buildCatalogProductsPath,
  createCatalogRepository,
} from '../domain/catalog/catalog.repository'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const apiFixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8'))

const productId = '22222222-2222-4222-8222-222222222222'
const brandId = '33333333-3333-4333-8333-333333333333'
const seriesId = '44444444-4444-4444-8444-444444444444'

function requestSequence(responses: unknown[]) {
  const requests: Array<{ url: string; options: FetchOptions }> = []
  const queue = [...responses]
  const requester: ApiRequester = async <T>(url: string, options: FetchOptions = {}) => {
    requests.push({ url, options })
    const body = queue.shift()
    if (body === undefined) throw new Error('No response configured')
    return body as T
  }
  return { requester, requests }
}

describe('API v2 catalog contract', () => {
  it('validates the shared list and facet fixtures', () => {
    const page = catalogProductsResponseSchema.parse(apiFixture('catalog_products_page.json'))
    const facets = catalogFacetsResponseSchema.parse(apiFixture('catalog_facets.json'))

    expect(page.data[0]?.id).toBe(productId)
    expect(page.data[0]?.clientPrice.amount).toBe('90.00')
    expect(page.meta.nextCursor).toBeNull()
    expect(facets.data.stockStatuses).toEqual(['IN_STOCK'])
    expect(facets.meta.requestId).toBe('v2-fixture-facets-001')
  })

  it('rejects snake_case, legacy fields, internal media keys, and unknown fields', () => {
    const snakeCase = apiFixture('catalog_products_page.json')
    snakeCase.data[0].stock_status = snakeCase.data[0].stockStatus
    delete snakeCase.data[0].stockStatus
    expect(catalogProductsResponseSchema.safeParse(snakeCase).success).toBe(false)

    const internalMedia = apiFixture('catalog_products_page.json')
    internalMedia.data[0].photoKey = 'photos-product/private/product.jpg'
    expect(catalogProductsResponseSchema.safeParse(internalMedia).success).toBe(false)

    const unknownEnvelopeField = apiFixture('catalog_products_page.json')
    unknownEnvelopeField.meta.total = 1
    expect(catalogProductsResponseSchema.safeParse(unknownEnvelopeField).success).toBe(false)

    const snakeCaseFacet = apiFixture('catalog_facets.json')
    snakeCaseFacet.meta.request_id = snakeCaseFacet.meta.requestId
    delete snakeCaseFacet.meta.requestId
    expect(catalogFacetsResponseSchema.safeParse(snakeCaseFacet).success).toBe(false)
  })

  it('serializes all list filters, repeated UUIDs, pagination, sort, and price mode', async () => {
    const page = apiFixture('catalog_products_page.json')
    const { requester, requests } = requestSequence([page])
    const repository = createCatalogRepository(createApiV2Client(requester))

    const result = await repository.list({
      q: 'щит A/B & C',
      brands: [brandId, '55555555-5555-4555-8555-555555555555'],
      series: [seriesId],
      stock: 'PREORDER',
      model: 'Щит распределительный',
      sort: '-price',
      limit: 25,
      cursor: 'opaque/cursor+value',
      priceCalcMode: 'nbrb_current',
    })

    const url = new URL(requests[0]?.url ?? '', 'http://catalog.test')
    expect(url.pathname).toBe('/api/v2/catalog/products')
    expect(url.searchParams.get('q')).toBe('щит A/B & C')
    expect(url.searchParams.getAll('brands')).toEqual([
      brandId,
      '55555555-5555-4555-8555-555555555555',
    ])
    expect(url.searchParams.getAll('series')).toEqual([seriesId])
    expect(url.searchParams.get('stock')).toBe('PREORDER')
    expect(url.searchParams.get('model')).toBe('Щит распределительный')
    expect(url.searchParams.get('sort')).toBe('-price')
    expect(url.searchParams.get('limit')).toBe('25')
    expect(url.searchParams.get('cursor')).toBe('opaque/cursor+value')
    expect(url.searchParams.get('price_calc_mode')).toBe('nbrb_current')
    expect(result.products[0]?.sku).toBe('V2-FIXTURE-1')
    expect(result.requestId).toBe('v2-fixture-catalog-001')
  })

  it('uses the same server-side search endpoint and omits empty filter arrays', async () => {
    const page = apiFixture('catalog_products_page.json')
    const { requester, requests } = requestSequence([page])
    const repository = createCatalogRepository(createApiV2Client(requester))

    await repository.search('V2/FIXTURE', {
      brands: [],
      series: [],
      limit: 10,
    })

    const url = new URL(requests[0]?.url ?? '', 'http://catalog.test')
    expect(url.pathname).toBe('/api/v2/catalog/products')
    expect(url.searchParams.get('q')).toBe('V2/FIXTURE')
    expect(url.searchParams.get('limit')).toBe('10')
    expect(url.searchParams.has('brands')).toBe(false)
    expect(url.searchParams.has('series')).toBe(false)
  })

  it('validates UUID identity and safely encodes SKU identity in detail paths', async () => {
    const page = apiFixture('catalog_products_page.json')
    const detail = {
      data: page.data[0],
      meta: { requestId: 'v2-fixture-catalog-detail-001' },
    }
    const { requester, requests } = requestSequence([detail, detail])
    const repository = createCatalogRepository(createApiV2Client(requester))

    const byId = await repository.getById(productId, 'fixed')
    const bySku = await repository.getBySku('V2 / SKU?#%', 'nbrb_current')

    expect(requests[0]?.url).toBe(`/api/v2/catalog/products/${productId}?price_calc_mode=fixed`)
    expect(requests[1]?.url).toBe(
      '/api/v2/catalog/products/by-sku/V2%20%2F%20SKU%3F%23%25?price_calc_mode=nbrb_current',
    )
    expect(byId.product.id).toBe(productId)
    expect(bySku.product.sku).toBe('V2-FIXTURE-1')
    expect(bySku.requestId).toBe('v2-fixture-catalog-detail-001')
  })

  it('rejects invalid UUID/SKU identities before issuing a request', async () => {
    const { requester, requests } = requestSequence([])
    const repository = createCatalogRepository(createApiV2Client(requester))

    await expect(repository.getById('not-a-uuid')).rejects.toThrow()
    await expect(repository.getBySku('')).rejects.toThrow()
    await expect(repository.getBySku('x'.repeat(129))).rejects.toThrow()
    expect(requests).toHaveLength(0)
  })

  it('returns validated facets and keeps malformed success payloads as contract errors', async () => {
    const facets = apiFixture('catalog_facets.json')
    const { requester } = requestSequence([facets, { data: {}, meta: { requestId: 'bad' } }])
    const repository = createCatalogRepository(createApiV2Client(requester))

    const result = await repository.getFacets()
    expect(result.facets.brands[0]?.id).toBe(brandId)
    expect(result.requestId).toBe('v2-fixture-facets-001')
    await expect(repository.getFacets()).rejects.toBeInstanceOf(ApiContractError)
  })

  it('rejects unsupported query values before serialization', () => {
    expect(() => buildCatalogProductsPath({ limit: 101 })).toThrow()
    expect(() => buildCatalogProductsPath({ brands: ['not-a-uuid'] })).toThrow()
    expect(() =>
      buildCatalogProductsPath({ sort: 'createdAt' } as unknown as {
        sort: 'name'
      }),
    ).toThrow()
  })
})
