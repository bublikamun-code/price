import type {
  ApiRequestMethod,
  ApiRequestOptions,
  ApiResponse,
  ApiV2Client,
} from '../api/v2/client'
import {
  cartResponseSchema,
  type CartItemAdd,
  type CartItemReplace,
  type CartResponse,
  type CartSummary,
} from '../api/v2/cart.schema'

export interface CartSnapshot {
  cart: CartSummary
  etag: string
  requestId: string
}

export interface CartRepository {
  getCurrent(): Promise<CartSnapshot>
  addItem(payload: CartItemAdd, ifMatch: string): Promise<CartSnapshot>
  replaceItem(productId: string, payload: CartItemReplace, ifMatch: string): Promise<CartSnapshot>
  removeItem(productId: string, ifMatch: string): Promise<CartSnapshot>
  clear(ifMatch: string): Promise<CartSnapshot>
}

function snapshot(response: ApiResponse<CartResponse>): CartSnapshot {
  return {
    cart: response.data.data,
    etag: response.etag ?? `"${response.data.data.version}"`,
    requestId: response.data.meta.requestId,
  }
}

export function createCartRepository(client: ApiV2Client): CartRepository {
  const getCurrent = () =>
    client
      .execute('/api/v2/cart', cartResponseSchema, { method: 'GET' })
      .then(snapshot)

  const write = (
    method: Extract<ApiRequestMethod, 'POST' | 'PUT' | 'DELETE'>,
    path: string,
    payload: ApiRequestOptions['body'],
    ifMatch: string,
  ): Promise<CartSnapshot> =>
    client
      .execute(path, cartResponseSchema, {
        method,
        body: payload,
        headers: { 'If-Match': ifMatch },
      })
      .then(snapshot)

  return {
    getCurrent,
    addItem(payload, ifMatch) {
      return write('POST', '/api/v2/cart/items', payload, ifMatch)
    },
    replaceItem(productId, payload, ifMatch) {
      return write('PUT', `/api/v2/cart/items/${productId}`, payload, ifMatch)
    },
    removeItem(productId, ifMatch) {
      return write('DELETE', `/api/v2/cart/items/${productId}`, undefined, ifMatch)
    },
    clear(ifMatch) {
      return write('DELETE', '/api/v2/cart', undefined, ifMatch)
    },
  }
}
