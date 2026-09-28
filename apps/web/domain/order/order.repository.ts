import type { CartSummary } from "../api/v2/cart.schema";
import type { ApiResponse, ApiV2Client } from "../api/v2/client";
import {
  orderListQuerySchema,
  orderListResponseSchema,
  orderRepeatResponseSchema,
  orderResponseSchema,
  type OrderCreate,
  type OrderDetail,
  type OrderListQuery,
  type OrderListResponse,
  type OrderRepeatResponse,
  type OrderResponse,
  type OrderSummary,
} from "../api/v2/order.schema";

export interface OrderCreateResult {
  order: OrderDetail;
  requestId: string;
  idempotencyReplayed: boolean;
}

export interface OrderPage {
  orders: OrderSummary[];
  requestId: string;
  nextCursor: string | null;
  hasMore: boolean;
  limit: number;
  sort: "createdAt,id";
}

export interface OrderSnapshot {
  order: OrderDetail;
  requestId: string;
}

export interface OrderRepeatResult {
  cart: CartSummary;
  etag: string;
  requestId: string;
}

export interface OrderRepository {
  list(params?: OrderListQuery): Promise<OrderPage>;
  getById(orderId: string): Promise<OrderSnapshot>;
  create(
    payload: OrderCreate,
    idempotencyKey: string,
  ): Promise<OrderCreateResult>;
  cancel(orderId: string): Promise<OrderSnapshot>;
  repeat(orderId: string, ifMatch: string): Promise<OrderRepeatResult>;
}

function createResult(response: ApiResponse<OrderResponse>): OrderCreateResult {
  return {
    order: response.data.data,
    requestId: response.data.meta.requestId,
    idempotencyReplayed: response.idempotencyReplayed,
  };
}

function snapshot(response: ApiResponse<OrderResponse>): OrderSnapshot {
  return {
    order: response.data.data,
    requestId: response.data.meta.requestId,
  };
}

function page(response: ApiResponse<OrderListResponse>): OrderPage {
  return {
    orders: response.data.data,
    requestId: response.data.meta.requestId,
    nextCursor: response.data.meta.nextCursor,
    hasMore: response.data.meta.hasMore,
    limit: response.data.meta.limit,
    sort: response.data.meta.sort,
  };
}

function repeated(
  response: ApiResponse<OrderRepeatResponse>,
): OrderRepeatResult {
  return {
    cart: response.data.data,
    etag: response.etag ?? `"${response.data.data.version}"`,
    requestId: response.data.meta.requestId,
  };
}

function listPath(params: OrderListQuery = {}): string {
  const query = orderListQuerySchema.parse(params);
  const search = new URLSearchParams();

  if (query.status) search.set("status", query.status);
  if (query.q !== undefined) search.set("q", query.q);
  if (query.dateFrom !== undefined) search.set("date_from", query.dateFrom);
  if (query.dateTo !== undefined) search.set("date_to", query.dateTo);
  if (query.minTotal !== undefined) search.set("min_total", query.minTotal);
  if (query.maxTotal !== undefined) search.set("max_total", query.maxTotal);
  if (query.limit !== undefined) search.set("limit", String(query.limit));
  if (query.cursor !== undefined) search.set("cursor", query.cursor);

  const encoded = search.toString();
  return encoded ? `/api/v2/orders?${encoded}` : "/api/v2/orders";
}

export function createOrderRepository(client: ApiV2Client): OrderRepository {
  return {
    list(params) {
      return client
        .execute(listPath(params), orderListResponseSchema, { method: "GET" })
        .then(page);
    },
    getById(orderId) {
      return client
        .execute(`/api/v2/orders/${orderId}`, orderResponseSchema, {
          method: "GET",
        })
        .then(snapshot);
    },
    create(payload, idempotencyKey) {
      return client
        .execute("/api/v2/orders", orderResponseSchema, {
          method: "POST",
          body: payload,
          headers: { "Idempotency-Key": idempotencyKey },
        })
        .then(createResult);
    },
    cancel(orderId) {
      return client
        .execute(`/api/v2/orders/${orderId}/cancel`, orderResponseSchema, {
          method: "POST",
        })
        .then(snapshot);
    },
    repeat(orderId, ifMatch) {
      return client
        .execute(
          `/api/v2/orders/${orderId}/repeat`,
          orderRepeatResponseSchema,
          {
            method: "POST",
            headers: { "If-Match": ifMatch },
          },
        )
        .then(repeated);
    },
  };
}
