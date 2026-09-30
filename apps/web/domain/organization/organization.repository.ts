import type { ApiResponse, ApiV2Client } from '../api/v2/client'
import {
  organizationAddressCreateSchema,
  organizationAddressListResponseSchema,
  organizationAddressResponseSchema,
  organizationListQuerySchema,
  organizationListResponseSchema,
  organizationDetailResponseSchema,
  type OrganizationAddress,
  type OrganizationAddressCreate,
  type OrganizationAddressListResponse,
  type OrganizationAddressResponse,
  type OrganizationDetail,
  type OrganizationListQuery,
  type OrganizationListResponse,
  type OrganizationResponse,
  type OrganizationSummary,
} from '../api/v2/organizations.schema'

export interface OrganizationAddressSnapshot {
  address: OrganizationAddress
  requestId: string
}

export interface OrganizationAddressList {
  addresses: OrganizationAddress[]
  requestId: string
}

/** Страница коллекции организаций (server-side cursor, §6). */
export interface OrganizationPage {
  organizations: OrganizationSummary[]
  requestId: string
  nextCursor: string | null
  hasMore: boolean
  limit: number
  sort: string
}

export interface OrganizationSnapshot {
  organization: OrganizationDetail
  requestId: string
}

export interface OrganizationRepository {
  list(params?: OrganizationListQuery): Promise<OrganizationPage>
  getById(organizationId: string): Promise<OrganizationSnapshot>
  listAddresses(): Promise<OrganizationAddressList>
  createAddress(
    payload: OrganizationAddressCreate,
    idempotencyKey: string,
  ): Promise<OrganizationAddressSnapshot>
}

function detailSnapshot(response: ApiResponse<OrganizationResponse>): OrganizationSnapshot {
  return {
    organization: response.data.data,
    requestId: response.data.meta.requestId,
  }
}

function organizationPage(
  response: ApiResponse<OrganizationListResponse>,
): OrganizationPage {
  return {
    organizations: response.data.data,
    requestId: response.data.meta.requestId,
    nextCursor: response.data.meta.nextCursor,
    hasMore: response.data.meta.hasMore,
    limit: response.data.meta.limit,
    sort: response.data.meta.sort,
  }
}

function snapshot(
  response: ApiResponse<OrganizationAddressResponse>,
): OrganizationAddressSnapshot {
  return {
    address: response.data.data,
    requestId: response.data.meta.requestId,
  }
}

function list(
  response: ApiResponse<OrganizationAddressListResponse>,
): OrganizationAddressList {
  return {
    addresses: response.data.data,
    requestId: response.data.meta.requestId,
  }
}

/** Путь коллекции организаций: server-side q/sort/cursor (§6). */
function listPath(params: OrganizationListQuery = {}): string {
  const query = organizationListQuerySchema.parse(params)
  const search = new URLSearchParams()

  if (query.q !== undefined) search.set('q', query.q)
  if (query.sort) search.set('sort', query.sort)
  if (query.limit !== undefined) search.set('limit', String(query.limit))
  if (query.cursor !== undefined) search.set('cursor', query.cursor)

  const encoded = search.toString()
  return encoded ? `/api/v2/organizations?${encoded}` : '/api/v2/organizations'
}

export function createOrganizationRepository(client: ApiV2Client): OrganizationRepository {
  return {
    list(params) {
      return client
        .execute(listPath(params), organizationListResponseSchema, { method: 'GET' })
        .then(organizationPage)
    },
    getById(organizationId) {
      return client
        .execute(`/api/v2/organizations/${organizationId}`, organizationDetailResponseSchema, {
          method: 'GET',
        })
        .then(detailSnapshot)
    },
    listAddresses() {
      return client
        .execute(
          '/api/v2/me/organization/addresses',
          organizationAddressListResponseSchema,
          { method: 'GET' },
        )
        .then(list)
    },
    async createAddress(payload, idempotencyKey) {
      // Тело валидируется до отправки: мусор не уходит в сеть, addressLine
      // нормализуется (trim), лишние ключи отсекаются схемой.
      const body = organizationAddressCreateSchema.parse(payload)
      return client
        .execute(
          '/api/v2/me/organization/addresses',
          organizationAddressResponseSchema,
          {
            method: 'POST',
            body,
            headers: { 'Idempotency-Key': idempotencyKey },
          },
        )
        .then(snapshot)
    },
  }
}
