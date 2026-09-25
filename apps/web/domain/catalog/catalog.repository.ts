import type { ApiV2Client } from '../api/v2/client'
import {
  catalogFacetsResponseSchema,
  catalogListQuerySchema,
  catalogPriceCalcModeSchema,
  catalogProductIdSchema,
  catalogProductResponseSchema,
  catalogProductSkuSchema,
  catalogProductsResponseSchema,
  type CatalogFacets,
  type CatalogListQuery,
  type CatalogPriceCalcMode,
  type CatalogProduct,
  type CatalogProductId,
  type CatalogProductSku,
  type CatalogProductsResponse,
  type CatalogSort,
} from '../api/v2/catalog.schema'

const productsPath = '/api/v2/catalog/products'

export type CatalogSearchQuery = Omit<CatalogListQuery, 'q'>

export interface CatalogListResult {
  products: CatalogProduct[]
  requestId: string
  nextCursor: string | null
  hasMore: boolean
  limit: number
  sort: CatalogSort
}

export interface CatalogProductResult {
  product: CatalogProduct
  requestId: string
}

export interface CatalogFacetsResult {
  facets: CatalogFacets
  requestId: string
}

export interface CatalogRepository {
  list(query?: CatalogListQuery): Promise<CatalogListResult>
  search(q: string, query?: CatalogSearchQuery): Promise<CatalogListResult>
  getById(
    productId: CatalogProductId,
    priceCalcMode?: CatalogPriceCalcMode,
  ): Promise<CatalogProductResult>
  getBySku(
    sku: CatalogProductSku,
    priceCalcMode?: CatalogPriceCalcMode,
  ): Promise<CatalogProductResult>
  getFacets(): Promise<CatalogFacetsResult>
}

export function buildCatalogProductsPath(query: CatalogListQuery = {}): string {
  const parsed = catalogListQuerySchema.parse(query)
  const params = new URLSearchParams()

  if (parsed.q !== undefined) params.set('q', parsed.q)
  parsed.brands?.forEach((brandId) => params.append('brands', brandId))
  parsed.series?.forEach((seriesId) => params.append('series', seriesId))
  if (parsed.stock !== undefined) params.set('stock', parsed.stock)
  if (parsed.model !== undefined) params.set('model', parsed.model)
  if (parsed.sort !== undefined) params.set('sort', parsed.sort)
  if (parsed.limit !== undefined) params.set('limit', String(parsed.limit))
  if (parsed.cursor !== undefined) params.set('cursor', parsed.cursor)
  if (parsed.priceCalcMode !== undefined) {
    params.set('price_calc_mode', parsed.priceCalcMode)
  }

  const serialized = params.toString()
  return serialized ? `${productsPath}?${serialized}` : productsPath
}

function withPriceCalcMode(path: string, priceCalcMode?: CatalogPriceCalcMode): string {
  if (priceCalcMode === undefined) return path
  const params = new URLSearchParams({
    price_calc_mode: catalogPriceCalcModeSchema.parse(priceCalcMode),
  })
  return `${path}?${params.toString()}`
}

function listResult(response: CatalogProductsResponse): CatalogListResult {
  return {
    products: response.data,
    requestId: response.meta.requestId,
    nextCursor: response.meta.nextCursor,
    hasMore: response.meta.hasMore,
    limit: response.meta.limit,
    sort: response.meta.sort,
  }
}

function productResult(response: {
  data: CatalogProduct
  meta: { requestId: string }
}): CatalogProductResult {
  return {
    product: response.data,
    requestId: response.meta.requestId,
  }
}

export function createCatalogRepository(client: ApiV2Client): CatalogRepository {
  const list = async (query: CatalogListQuery = {}) =>
    client.get(buildCatalogProductsPath(query), catalogProductsResponseSchema).then(listResult)

  return {
    list,
    search(q, query = {}) {
      return list({ ...query, q })
    },
    async getById(productId, priceCalcMode) {
      const id = catalogProductIdSchema.parse(productId)
      const path = withPriceCalcMode(`${productsPath}/${id}`, priceCalcMode)
      return client.get(path, catalogProductResponseSchema).then(productResult)
    },
    async getBySku(sku, priceCalcMode) {
      const productSku = catalogProductSkuSchema.parse(sku)
      const path = withPriceCalcMode(
        `${productsPath}/by-sku/${encodeURIComponent(productSku)}`,
        priceCalcMode,
      )
      return client.get(path, catalogProductResponseSchema).then(productResult)
    },
    getFacets() {
      return client.get('/api/v2/catalog/facets', catalogFacetsResponseSchema).then((response) => ({
        facets: response.data,
        requestId: response.meta.requestId,
      }))
    },
  }
}
