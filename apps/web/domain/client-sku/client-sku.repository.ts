import type { ApiResponse, ApiV2Client } from '../api/v2/client'
import { uuidSchema } from '../api/v2/common.schema'
import {
  applyCsvRequestSchema,
  applyCsvResponseSchema,
  clientSkuMappingCreateSchema,
  clientSkuMappingDeleteResponseSchema,
  clientSkuMappingListQuerySchema,
  clientSkuMappingListResponseSchema,
  clientSkuMappingResponseSchema,
  clientSkuMappingUpdateSchema,
  type ApplyCsvResponse,
  type ClientSkuMapping,
  type ClientSkuMappingCreate,
  type ClientSkuMappingListQuery,
  type ClientSkuMappingListResponse,
  type ClientSkuMappingResponse,
  type ClientSkuMappingUpdate,
} from '../api/v2/client-sku.schema'
import { toIfMatch } from '../invoice/invoice.repository'

/**
 * Кросс-справочник клиентских артикулов (Этап 7). Тонкая обёртка над v2:
 * валидирует и то, что уходит, и то, что приходит, и ничего не знает про UI.
 *
 * Клиентские операции ({list,create,update,remove,applyCsv}) идут на
 * `/api/v2/me/organization/client-sku-mappings` — организация резолвится на
 * бэке из сессии. Менеджерские (*ForOrg) — на
 * `/api/v2/manager/organizations/{organizationId}/client-sku-mappings`
 * (только MANAGER/ADMIN, права проверяет бэк).
 *
 * `If-Match` PATCH собирается из `version` связки — формат ETag в кавычках,
 * как его ждёт `parse_if_match` на бэке (см. toIfMatch в invoice.repository).
 */
export interface ClientSkuMappingPage {
  mappings: ClientSkuMapping[]
  page: number
  pageSize: number
  total: number
  requestId: string | null
}

export interface ClientSkuMappingSnapshot {
  mapping: ClientSkuMapping
  requestId: string | null
}

export interface ApplyCsvResult {
  rows: ApplyCsvResponse['data']['rows']
  summary: ApplyCsvResponse['data']['summary']
  cartVersion: ApplyCsvResponse['data']['cartVersion']
  requestId: string | null
}

export interface ClientSkuRepository {
  list(params?: ClientSkuMappingListQuery): Promise<ClientSkuMappingPage>
  create(
    payload: ClientSkuMappingCreate,
    idempotencyKey?: string,
  ): Promise<ClientSkuMappingSnapshot>
  update(
    mappingId: string,
    version: number,
    patch: ClientSkuMappingUpdate,
  ): Promise<ClientSkuMappingSnapshot>
  remove(mappingId: string): Promise<void>
  applyCsv(csv: string): Promise<ApplyCsvResult>
  listForOrg(
    organizationId: string,
    params?: ClientSkuMappingListQuery,
  ): Promise<ClientSkuMappingPage>
  createForOrg(
    organizationId: string,
    payload: ClientSkuMappingCreate,
    idempotencyKey?: string,
  ): Promise<ClientSkuMappingSnapshot>
  removeForOrg(organizationId: string, mappingId: string): Promise<void>
}

const mePath = '/api/v2/me/organization/client-sku-mappings'

function managerPath(organizationId: string, suffix = ''): string {
  return `/api/v2/manager/organizations/${uuidSchema.parse(organizationId)}/client-sku-mappings${suffix}`
}

function listPath(base: string, params: ClientSkuMappingListQuery = {}): string {
  const query = clientSkuMappingListQuerySchema.parse(params)
  const search = new URLSearchParams()

  if (query.query) search.set('query', query.query)
  if (query.page !== undefined) search.set('page', String(query.page))
  if (query.pageSize !== undefined) search.set('pageSize', String(query.pageSize))

  const encoded = search.toString()
  return encoded ? `${base}?${encoded}` : base
}

function page(response: ApiResponse<ClientSkuMappingListResponse>): ClientSkuMappingPage {
  return {
    mappings: response.data.data,
    page: response.data.meta.page,
    pageSize: response.data.meta.pageSize,
    total: response.data.meta.total,
    requestId: response.data.meta.requestId,
  }
}

function snapshot(response: ApiResponse<ClientSkuMappingResponse>): ClientSkuMappingSnapshot {
  return {
    mapping: response.data.data,
    requestId: response.data.meta.requestId,
  }
}

function applied(response: ApiResponse<ApplyCsvResponse>): ApplyCsvResult {
  return {
    rows: response.data.data.rows,
    summary: response.data.data.summary,
    cartVersion: response.data.data.cartVersion,
    requestId: response.data.meta.requestId,
  }
}

export function createClientSkuRepository(client: ApiV2Client): ClientSkuRepository {
  const list = async (base: string, params?: ClientSkuMappingListQuery) =>
    client.execute(listPath(base, params), clientSkuMappingListResponseSchema, {
      method: 'GET',
    }).then(page)

  const create = async (base: string, payload: ClientSkuMappingCreate, idempotencyKey?: string) => {
    // Тело валидируется до отправки: мусор не уходит в сеть, clientSku
    // нормализуется (trim), лишние ключи отсекаются схемой.
    const body = clientSkuMappingCreateSchema.parse(payload)
    return client
      .execute(base, clientSkuMappingResponseSchema, {
        method: 'POST',
        body,
        ...(idempotencyKey ? { headers: { 'Idempotency-Key': idempotencyKey } } : {}),
      })
      .then(snapshot)
  }

  const remove = async (base: string) => {
    await client.execute(base, clientSkuMappingDeleteResponseSchema, { method: 'DELETE' })
  }

  return {
    list(params) {
      return list(mePath, params)
    },
    create(payload, idempotencyKey) {
      return create(mePath, payload, idempotencyKey)
    },
    async update(mappingId, version, patch) {
      const id = uuidSchema.parse(mappingId)
      return client
        .execute(`${mePath}/${id}`, clientSkuMappingResponseSchema, {
          method: 'PATCH',
          body: clientSkuMappingUpdateSchema.parse(patch),
          headers: { 'If-Match': toIfMatch(version) },
        })
        .then(snapshot)
    },
    remove(mappingId) {
      return remove(`${mePath}/${uuidSchema.parse(mappingId)}`)
    },
    async applyCsv(csv) {
      return client
        .execute(`${mePath}/apply-csv`, applyCsvResponseSchema, {
          method: 'POST',
          body: applyCsvRequestSchema.parse({ csv }),
        })
        .then(applied)
    },
    listForOrg(organizationId, params) {
      return list(managerPath(organizationId), params)
    },
    createForOrg(organizationId, payload, idempotencyKey) {
      return create(managerPath(organizationId), payload, idempotencyKey)
    },
    removeForOrg(organizationId, mappingId) {
      return remove(
        `${managerPath(organizationId)}/${uuidSchema.parse(mappingId)}`,
      )
    },
  }
}
