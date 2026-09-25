import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { FetchOptions } from "ofetch";
import { describe, expect, it } from "vitest";

import {
  ApiContractError,
  createApiV2Client,
  type ApiRequester,
} from "../domain/api/v2/client";
import {
  orderCreateSchema,
  orderListQuerySchema,
  orderListResponseSchema,
  orderRepeatResponseSchema,
  orderResponseSchema,
} from "../domain/api/v2/order.schema";
import { AppProblem } from "../domain/api/v2/problem";
import { createOrderRepository } from "../domain/order/order.repository";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const apiFixture = (name: string) =>
  JSON.parse(
    readFileSync(resolve(webRoot, "../api/tests/fixtures/v2", name), "utf8"),
  );

interface RecordedRequest {
  url: string;
  options: FetchOptions;
}

function requestSequence(
  responses: Array<{
    body?: unknown;
    replayed?: boolean;
    etag?: string;
    error?: unknown;
  }>,
) {
  const requests: RecordedRequest[] = [];
  const queue = [...responses];
  const requester: ApiRequester = async <T>(
    url: string,
    options: FetchOptions = {},
  ) => {
    requests.push({ url, options });
    const current = queue.shift();
    if (!current) throw new Error("No response configured");
    if (current.error) throw current.error;

    const hooks = Array.isArray(options.onResponse)
      ? options.onResponse
      : options.onResponse
        ? [options.onResponse]
        : [];
    const response = new Response(null, {
      headers: {
        ...(current.replayed === undefined
          ? {}
          : { "x-idempotency-replayed": String(current.replayed) }),
        ...(current.etag === undefined ? {} : { etag: current.etag }),
      },
    });
    for (const hook of hooks) await hook({ response } as never);
    return current.body as T;
  };
  return { requester, requests };
}

describe("API v2 order contract", () => {
  it("validates the shared create and detail fixtures", () => {
    const create = apiFixture("order_create_request.json");
    const response = apiFixture("order_create_success.json");

    expect(orderCreateSchema.parse(create).items[0]?.quantity).toBe("6");
    const parsed = orderResponseSchema.parse(response);
    expect(parsed.data.status).toBe("NEW");
    expect(parsed.data.organizationId).toBeNull();
    expect(parsed.data.lines[0]?.quantity).toBe(6);
    expect(parsed.meta.requestId).toBe("v2-fixture-order-create-001");
  });

  it("validates the cursor list summary, Money, Rate, and strict camelCase envelope", () => {
    const response = apiFixture("order_list_page.json");
    const parsed = orderListResponseSchema.parse(response);

    expect(parsed.data[0]).toMatchObject({
      id: "88888888-8888-4888-8888-888888888888",
      organizationId: "22222222-2222-4222-8222-222222222222",
      total: { amount: "125.50", currency: "BYN" },
      exchangeRate: { value: "1.0000", scale: 4, source: "BYN" },
    });
    expect(parsed.data[0]).not.toHaveProperty("lines");
    expect(parsed.meta).toEqual({
      requestId: "v2-fixture-order-list-001",
      nextCursor: null,
      hasMore: false,
      limit: 50,
      sort: "createdAt,id",
    });

    const legacy = apiFixture("order_list_page.json");
    legacy.data[0].created_at = legacy.data[0].createdAt;
    delete legacy.data[0].createdAt;
    expect(orderListResponseSchema.safeParse(legacy).success).toBe(false);

    expect(
      orderListQuerySchema.safeParse({
        status: "IN_PROGRESS",
        limit: 100,
        cursor: "opaque",
      }).success,
    ).toBe(true);
    expect(orderListQuerySchema.safeParse({ limit: 101 }).success).toBe(false);
  });

  it("lists summary orders with encoded status, limit, and opaque cursor parameters", async () => {
    const response = apiFixture("order_list_page.json");
    response.meta.nextCursor = "next-page+/=";
    response.meta.hasMore = true;
    response.meta.limit = 20;
    const { requester, requests } = requestSequence([{ body: response }]);
    const repository = createOrderRepository(createApiV2Client(requester));

    const result = await repository.list({
      status: "IN_PROGRESS",
      limit: 20,
      cursor: "cursor+/=",
    });

    expect(result.orders).toHaveLength(1);
    expect(result.nextCursor).toBe("next-page+/=");
    expect(result.hasMore).toBe(true);
    expect(result.sort).toBe("createdAt,id");
    expect(requests[0]?.url).toBe(
      "/api/v2/orders?status=IN_PROGRESS&limit=20&cursor=cursor%2B%2F%3D",
    );
    expect(requests[0]?.options.method).toBe("GET");
    expect(requests[0]?.options.body).toBeUndefined();
    expect(requests[0]?.options.headers).toBeUndefined();
  });

  it("reads order detail by UUID with GET and no request body", async () => {
    const response = apiFixture("order_detail_success.json");
    const { requester, requests } = requestSequence([{ body: response }]);
    const repository = createOrderRepository(createApiV2Client(requester));
    const orderId = "88888888-8888-4888-8888-888888888888";

    const result = await repository.getById(orderId);

    expect(result.order.lines[1]?.lineTotal).toEqual({
      amount: "45.00",
      currency: "BYN",
    });
    expect(result.requestId).toBe("v2-fixture-order-detail-001");
    expect(requests[0]?.url).toBe(`/api/v2/orders/${orderId}`);
    expect(requests[0]?.options.method).toBe("GET");
    expect(requests[0]?.options.body).toBeUndefined();
    expect(requests[0]?.options.headers).toBeUndefined();
  });

  it("cancels an order without inventing a backend If-Match contract", async () => {
    const response = apiFixture("order_detail_success.json");
    response.data.status = "CANCELLED";
    response.data.updatedAt = "2026-08-21T09:30:00Z";
    response.data.version = 2;
    const { requester, requests } = requestSequence([{ body: response }]);
    const repository = createOrderRepository(createApiV2Client(requester));
    const orderId = "88888888-8888-4888-8888-888888888888";

    const result = await repository.cancel(orderId);

    expect(result.order.status).toBe("CANCELLED");
    expect(result.order.version).toBe(2);
    expect(requests[0]?.url).toBe(`/api/v2/orders/${orderId}/cancel`);
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.body).toBeUndefined();
    expect(requests[0]?.options.headers).toBeUndefined();
  });

  it("repeats an order into the scoped cart with If-Match and a new ETag", async () => {
    const response = apiFixture("cart_repeat_success.json");
    const { requester, requests } = requestSequence([
      { body: response, etag: '"2"' },
    ]);
    const repository = createOrderRepository(createApiV2Client(requester));
    const orderId = "88888888-8888-4888-8888-888888888888";

    const result = await repository.repeat(orderId, '"1"');

    expect(orderRepeatResponseSchema.parse(response).data.totalItems).toBe(1);
    expect(result.cart.total).toEqual({ amount: "40.00", currency: "BYN" });
    expect(result.etag).toBe('"2"');
    expect(result.requestId).toBe("v2-fixture-cart-repeat-001");
    expect(requests[0]?.url).toBe(`/api/v2/orders/${orderId}/repeat`);
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.headers).toEqual({ "If-Match": '"1"' });
    expect(requests[0]?.options.body).toBeUndefined();
  });

  it("keeps v2 Problem Details distinct from response contract errors", async () => {
    const notFound = apiFixture("problem_order_not_found.json");
    const stale = apiFixture("problem_stale_cart_version.json");
    const { requester } = requestSequence([
      { error: { data: notFound } },
      { error: { data: stale } },
    ]);
    const repository = createOrderRepository(createApiV2Client(requester));
    const orderId = "88888888-8888-4888-8888-888888888888";

    await expect(repository.getById(orderId)).rejects.toMatchObject({
      name: "AppProblem",
      code: "ORDER_NOT_FOUND",
      status: 404,
      requestId: "v2-fixture-order-not-found-001",
      isProblemDetails: true,
      retryable: false,
    });
    const problem = await repository
      .repeat(orderId, '"1"')
      .then(() => null)
      .catch((cause: unknown) => cause);

    expect(problem).toBeInstanceOf(AppProblem);
    expect(problem).toMatchObject({
      code: "STALE_RESOURCE_VERSION",
      status: 409,
      requestId: "v2-fixture-cart-stale-001",
      isProblemDetails: true,
      retryable: false,
    });
  });

  it("rejects legacy fields, organization scope in the body, and internal media keys", () => {
    const create = apiFixture("order_create_request.json");
    expect(
      orderCreateSchema.safeParse({ ...create, organizationId: null }).success,
    ).toBe(false);

    const response = apiFixture("order_create_success.json");
    response.data.lines[0].photoKey = "orders/private/photo.jpg";
    expect(orderResponseSchema.safeParse(response).success).toBe(false);

    const legacy = apiFixture("order_create_request.json");
    legacy.items[0].product_id = legacy.items[0].productId;
    delete legacy.items[0].productId;
    expect(orderCreateSchema.safeParse(legacy).success).toBe(false);
  });

  it("accepts only canonical positive quantity strings and rejects duplicate lines", () => {
    const create = apiFixture("order_create_request.json");
    expect(
      orderCreateSchema.safeParse({
        ...create,
        items: [{ ...create.items[0], quantity: "02" }],
      }).success,
    ).toBe(false);
    expect(
      orderCreateSchema.safeParse({
        ...create,
        items: [{ ...create.items[0], quantity: 6 }],
      }).success,
    ).toBe(false);
    expect(
      orderCreateSchema.safeParse({
        ...create,
        items: [create.items[0], create.items[0]],
      }).success,
    ).toBe(false);
  });

  it("posts UUID lines with Idempotency-Key and no If-Match or organizationId", async () => {
    const payload = apiFixture("order_create_request.json");
    const response = apiFixture("order_create_success.json");
    const { requester, requests } = requestSequence([
      { body: response, replayed: false },
    ]);
    const repository = createOrderRepository(createApiV2Client(requester));

    const result = await repository.create(payload, "order-submit-1");

    expect(result.order.id).toBe("88888888-8888-4888-8888-888888888888");
    expect(result.idempotencyReplayed).toBe(false);
    expect(requests[0]?.url).toBe("/api/v2/orders");
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.headers).toMatchObject({
      "Idempotency-Key": "order-submit-1",
    });
    expect(requests[0]?.options.headers).not.toHaveProperty("If-Match");
    expect(requests[0]?.options.body).toEqual(payload);
    expect(JSON.stringify(requests[0]?.options.body)).not.toContain(
      "organizationId",
    );
  });

  it("exposes server replay metadata without changing the get contract", async () => {
    const response = apiFixture("order_create_success.json");
    const { requester } = requestSequence([{ body: response, replayed: true }]);
    const client = createApiV2Client(requester);

    const result = await client.execute("/api/v2/orders", orderResponseSchema, {
      method: "POST",
      body: apiFixture("order_create_request.json"),
      headers: { "Idempotency-Key": "order-submit-1" },
    });

    expect(result.idempotencyReplayed).toBe(true);
    expect(result.etag).toBeNull();
  });

  it("maps idempotency conflicts to AppProblem", async () => {
    const problem = {
      data: {
        type: "https://priceweb.local/problems/idempotency-key-reused",
        title: "Конфликт идемпотентности",
        status: 409,
        detail: "Ключ уже использован для другого payload",
        code: "IDEMPOTENCY_KEY_REUSED",
        requestId: "v2-order-conflict-001",
      },
    };
    const { requester } = requestSequence([{ error: problem }]);
    const repository = createOrderRepository(createApiV2Client(requester));

    await expect(
      repository.create(
        apiFixture("order_create_request.json"),
        "order-submit-1",
      ),
    ).rejects.toMatchObject({
      code: "IDEMPOTENCY_KEY_REUSED",
      status: 409,
      requestId: "v2-order-conflict-001",
    });
  });

  it("keeps malformed successful order responses as contract errors", async () => {
    const { requester } = requestSequence([
      { body: { data: {}, meta: { requestId: "x" } } },
    ]);
    const repository = createOrderRepository(createApiV2Client(requester));

    await expect(
      repository.create(
        apiFixture("order_create_request.json"),
        "order-submit-1",
      ),
    ).rejects.toBeInstanceOf(ApiContractError);
  });
});
