import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import { createApiV2Client, type ApiRequester } from '../domain/api/v2/client'
import { catalogProductResponseSchema } from '../domain/api/v2/catalog.schema'
import { createDocumentsRepository } from '../domain/documents/documents.repository'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const apiFixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8'))

const productId = '22222222-2222-4222-8222-222222222222'
const seriesId = '55555555-5555-4555-8555-555555555555'
const certificateId = '88888888-8888-4888-8888-888888888888'
const expiredId = '99999999-9999-4999-8999-999999999992'

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

describe('API v2 product documents contract', () => {
  it('carries product and series documents in the detail fixture, expired included', () => {
    const detail = catalogProductResponseSchema.parse(apiFixture('catalog_product_detail.json'))

    expect(detail.data.documents).toHaveLength(3)
    const expired = detail.data.documents?.find((doc) => doc.id === expiredId)
    // Просроченный документ помечается, а не скрывается (§16 п.38).
    expect(expired).toMatchObject({ isExpired: true, validUntil: '2024-12-31' })
    const seriesDoc = detail.data.documents?.find((doc) => doc.scope === 'series')
    expect(seriesDoc).toMatchObject({ type: 'DATASHEET', validUntil: null })
  })

  it('surfaces documents through getBySku and tolerates detail without documents', async () => {
    const detail = apiFixture('catalog_product_detail.json')
    const bare = apiFixture('catalog_product_detail.json')
    delete bare.data.documents
    expect(catalogProductResponseSchema.safeParse(bare).success).toBe(true)

    const { requester } = requestSequence([detail])
    const repository = createDocumentsRepository(createApiV2Client(requester))
    const docs = await repository.listForProduct(productId)
    expect(docs.map((doc) => doc.id)).toContain(certificateId)
  })

  it('rejects a malformed document payload as a contract error', () => {
    const broken = apiFixture('catalog_product_detail.json')
    const docs = broken.data.documents as Array<Record<string, unknown>>
    delete docs[0]?.isExpired
    expect(catalogProductResponseSchema.safeParse(broken).success).toBe(false)
  })

  it('uploads a product document as multipart with type and valid_until', async () => {
    const created = apiFixture('catalog_product_detail.json')
    const doc = (created.data.documents as Array<Record<string, unknown>>)[0] as Record<string, unknown>
    const { requester, requests } = requestSequence([{ data: doc, meta: created.meta }])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    const file = new File(['%PDF-1.4 test'], 'certificate-2026.pdf', { type: 'application/pdf' })
    const uploaded = await repository.uploadForProduct(productId, {
      file,
      type: 'CERTIFICATE',
      validUntil: '2027-03-31',
    })

    expect(requests[0]?.url).toBe(`/api/v2/manager/products/${productId}/documents`)
    expect(requests[0]?.options.method).toBe('POST')
    const body = requests[0]?.options.body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('type')).toBe('CERTIFICATE')
    expect(body.get('valid_until')).toBe('2027-03-31')
    expect((body.get('file') as File).name).toBe('certificate-2026.pdf')
    expect(uploaded.id).toBe(certificateId)
  })

  it('omits valid_until when the date is empty and uploads series documents', async () => {
    const created = apiFixture('catalog_product_detail.json')
    const doc = (created.data.documents as Array<Record<string, unknown>>)[1] as Record<string, unknown>
    const { requester, requests } = requestSequence([{ data: doc, meta: created.meta }])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    const file = new File(['%PDF-1.4 test'], 'datasheet.pdf', { type: 'application/pdf' })
    await repository.uploadForSeries(seriesId, { file, type: 'DATASHEET', validUntil: '' })

    expect(requests[0]?.url).toBe(`/api/v2/manager/series/${seriesId}/documents`)
    const body = requests[0]?.options.body as FormData
    expect(body.get('type')).toBe('DATASHEET')
    expect(body.has('valid_until')).toBe(false)
  })

  it('deletes a document accepting an empty 204 body', async () => {
    const { requester, requests } = requestSequence([''])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    await expect(repository.remove(expiredId)).resolves.toBeUndefined()
    expect(requests[0]?.url).toBe(`/api/v2/manager/documents/${expiredId}`)
    expect(requests[0]?.options.method).toBe('DELETE')
  })

  it('resolves series documents from the first visible product of the series', async () => {
    const page = apiFixture('catalog_products_page.json')
    const detail = apiFixture('catalog_product_detail.json')
    const { requester, requests } = requestSequence([page, detail])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    const docs = await repository.listForSeries(seriesId)

    // Список товаров серии → detail первого → только scope=series.
    expect(requests[0]?.url).toBe(`/api/v2/catalog/products?series=${seriesId}&sort=sku&limit=1`)
    expect(requests[1]?.url).toBe(`/api/v2/catalog/products/${productId}`)
    expect(docs.map((doc) => doc.id)).toEqual([
      '99999999-9999-4999-8999-999999999991',
    ])
  })

  it('keeps an empty series resolvable without a detail request', async () => {
    const page = apiFixture('catalog_products_page.json')
    page.data = []
    const { requester, requests } = requestSequence([page])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    await expect(repository.listForSeries(seriesId)).resolves.toEqual([])
    expect(requests).toHaveLength(1)
  })

  it('rejects invalid identity before issuing a request', async () => {
    const { requester, requests } = requestSequence([])
    const repository = createDocumentsRepository(createApiV2Client(requester))

    await expect(repository.uploadForProduct('not-a-uuid', {
      file: new File(['x'], 'x.pdf'),
      type: 'CERTIFICATE',
    })).rejects.toThrow()
    await expect(repository.remove('nope')).rejects.toThrow()
    expect(requests).toHaveLength(0)
  })
})
