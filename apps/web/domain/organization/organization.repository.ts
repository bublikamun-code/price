import type { ApiResponse, ApiV2Client } from '../api/v2/client'
import {
  organizationAddressCreateSchema,
  organizationAddressListResponseSchema,
  organizationAddressResponseSchema,
  type OrganizationAddress,
  type OrganizationAddressCreate,
  type OrganizationAddressListResponse,
  type OrganizationAddressResponse,
} from '../api/v2/organizations.schema'

export interface OrganizationAddressSnapshot {
  address: OrganizationAddress
  requestId: string
}

export interface OrganizationAddressList {
  addresses: OrganizationAddress[]
  requestId: string
}

export interface OrganizationRepository {
  listAddresses(): Promise<OrganizationAddressList>
  createAddress(
    payload: OrganizationAddressCreate,
    idempotencyKey: string,
  ): Promise<OrganizationAddressSnapshot>
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

export function createOrganizationRepository(client: ApiV2Client): OrganizationRepository {
  return {
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
