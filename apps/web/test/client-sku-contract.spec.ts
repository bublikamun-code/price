import { describe, expect, it } from "vitest";
import type { FetchOptions } from "ofetch";

import {
  ApiContractError,
  createApiV2Client,
  type ApiRequester,
} from "../domain/api/v2/client";
import {
  applyCsvResponseSchema,
  clientSkuMappingCreateSchema,
  clientSkuMappingListResponseSchema,
  clientSkuMappingResponseSchema,
  type ClientSkuMappingCreate,
} from "../domain/api/v2/client-sku.schema";
import { createClientSkuRepository } from "../domain/client-sku/client-sku.repository";

interface RecordedRequest {
  url: string;
  options: FetchOptions;
}

function requestSequence(
  responses: Array<{
    body?: unknown;
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
        ...(current.etag === undefined ? {} : { etag: current.etag }),
      },
    });
    for (const hook of hooks) await hook({ response } as never);
    return current.body as T;
  };
  return { requester, requests };
}

const mappingId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const mapping = {
  id: mappingId,
  organizationId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  clientSku: "МОЙ-100",
  productId: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  note: null,
  version: 3,
  createdAt: "2026-10-30T09:00:00Z",
  updatedAt: "2026-10-30T09:00:00Z",
};
const singleResponse = {
  data: mapping,
  meta: { requestId: "v2-fixture-client-sku-single-001" },
};
const listResponse = {
  data: [mapping],
  meta: { page: 1, pageSize: 20, total: 1, requestId: "v2-fixture-client-sku-list-001" },
};
// Строка отчёта без опциональных полей — UNKNOWN не несёт товарных аннотаций.
const applyCsvResponse = {
  data: {
    rows: [
      {
        clientSku: "МОЙ-100",
        qty: 2,
        status: "MATCHED",
        productId: mapping.productId,
        productName: "Кабель ВВГнг 3x2.5",
        productSku: "A-100",
        unitPrice: { amount: "12.34", currency: "BYN" },
        stockStatus: "IN_STOCK",
      },
      { clientSku: "МОЙ-999", qty: 1, status: "UNKNOWN", message: "Связка не найдена" },
    ],
    summary: { matched: 1, unknown: 1, ambiguous: 0, cartAdded: 1 },
    cartVersion: "5",
  },
  meta: { requestId: "v2-fixture-client-sku-apply-001" },
};

describe("API v2 client SKU mapping contract", () => {
  it("validates the strict camelCase envelopes", () => {
    const parsed = clientSkuMappingResponseSchema.parse(singleResponse);
    expect(parsed.data).toMatchObject({
      clientSku: "МОЙ-100",
      version: 3,
      note: null,
    });
    const page = clientSkuMappingListResponseSchema.parse(listResponse);
    expect(page.meta).toMatchObject({ page: 1, pageSize: 20, total: 1 });

    const applied = applyCsvResponseSchema.parse(applyCsvResponse);
    expect(applied.data.rows[1]).toMatchObject({
      clientSku: "МОЙ-999",
      status: "UNKNOWN",
    });
    // productId/productSku/unitPrice отсутствуют — штатно, а не ошибка контракта.
    expect(applied.data.rows[1].productId).toBeUndefined();
    expect(applied.data.rows[1].productSku).toBeUndefined();
    expect(applied.data.cartVersion).toBe("5");

    const snake = structuredClone(listResponse);
    snake.data[0] = { ...mapping, client_sku: mapping.clientSku } as typeof snake.data[number];
    delete (snake.data[0] as Record<string, unknown>).clientSku;
    expect(clientSkuMappingListResponseSchema.safeParse(snake).success).toBe(false);
  });

  it("lists mappings from the me-organization endpoint with page query", async () => {
    const { requester, requests } = requestSequence([{ body: listResponse }]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    const result = await repository.list({ query: "МОЙ", page: 2, pageSize: 20 });

    expect(result.mappings).toHaveLength(1);
    expect(result.total).toBe(1);
    expect(requests[0]?.url).toBe(
      "/api/v2/me/organization/client-sku-mappings?query=%D0%9C%D0%9E%D0%99&page=2&pageSize=20",
    );
    expect(requests[0]?.options.method).toBe("GET");
  });

  it("creates a mapping with a trimmed camelCase body and Idempotency-Key", async () => {
    const { requester, requests } = requestSequence([{ body: singleResponse }]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    const payload: ClientSkuMappingCreate = {
      clientSku: "  МОЙ-100  ",
      productId: mapping.productId,
    };
    const result = await repository.create(payload, "mapping-create-1");

    expect(result.mapping.id).toBe(mappingId);
    expect(requests[0]?.url).toBe("/api/v2/me/organization/client-sku-mappings");
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.headers).toMatchObject({
      "Idempotency-Key": "mapping-create-1",
    });
    expect(requests[0]?.options.body).toMatchObject({
      clientSku: "МОЙ-100",
      productId: mapping.productId,
    });
    expect(JSON.stringify(requests[0]?.options.body)).not.toContain("client_sku");
  });

  it("patches with If-Match version and removes with a 204-style empty body", async () => {
    const { requester, requests } = requestSequence([
      { body: singleResponse },
      { body: null },
    ]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    const updated = await repository.update(mappingId, 3, { note: "Старый артикул" });
    expect(updated.mapping.version).toBe(3);
    expect(requests[0]?.url).toBe(
      `/api/v2/me/organization/client-sku-mappings/${mappingId}`,
    );
    expect(requests[0]?.options.method).toBe("PATCH");
    expect(requests[0]?.options.headers).toMatchObject({ 'If-Match': '"3"' });
    expect(requests[0]?.options.body).toMatchObject({ note: "Старый артикул" });

    await repository.remove(mappingId);
    expect(requests[1]?.options.method).toBe("DELETE");
  });

  it("posts apply-csv with the raw list and parses the report", async () => {
    const { requester, requests } = requestSequence([{ body: applyCsvResponse }]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    const result = await repository.applyCsv("МОЙ-100=2\nМОЙ-999");

    expect(result.rows).toHaveLength(2);
    expect(result.summary).toMatchObject({ matched: 1, unknown: 1, cartAdded: 1 });
    expect(result.cartVersion).toBe("5");
    expect(requests[0]?.url).toBe("/api/v2/me/organization/client-sku-mappings/apply-csv");
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.body).toMatchObject({ csv: "МОЙ-100=2\nМОЙ-999" });
  });

  it("addresses manager endpoints per organization", async () => {
    const { requester, requests } = requestSequence([
      { body: listResponse },
      { body: singleResponse },
      { body: null },
    ]);
    const repository = createClientSkuRepository(createApiV2Client(requester));
    const organizationId = mapping.organizationId;

    const page = await repository.listForOrg(organizationId, { page: 1 });
    expect(page.mappings).toHaveLength(1);
    await repository.createForOrg(organizationId, {
      clientSku: "МОЙ-100",
      productId: mapping.productId,
    });
    await repository.removeForOrg(organizationId, mappingId);

    const base = `/api/v2/manager/organizations/${organizationId}/client-sku-mappings`;
    expect(requests[0]?.url).toBe(`${base}?page=1`);
    expect(requests[1]?.url).toBe(base);
    expect(requests[1]?.options.method).toBe("POST");
    expect(requests[2]?.url).toBe(`${base}/${mappingId}`);
    expect(requests[2]?.options.method).toBe("DELETE");
  });

  it("rejects malformed create payloads before issuing a request", async () => {
    const { requester, requests } = requestSequence([]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    expect(
      clientSkuMappingCreateSchema.safeParse({
        clientSku: "   ",
        productId: mapping.productId,
      }).success,
    ).toBe(false);
    expect(
      clientSkuMappingCreateSchema.safeParse({
        clientSku: "МОЙ-100",
        productId: "not-a-uuid",
      }).success,
    ).toBe(false);
    expect(
      clientSkuMappingCreateSchema.safeParse({
        clientSku: "МОЙ-100",
        productId: mapping.productId,
        extra: true,
      }).success,
    ).toBe(false);

    await expect(
      repository.create({ clientSku: "", productId: mapping.productId }),
    ).rejects.toBeTruthy();
    expect(requests).toHaveLength(0);
  });

  it("maps the duplicate conflict to an AppProblem without retry", async () => {
    const problem = {
      data: {
        type: "https://priceweb.local/problems/client-sku-mapping-exists",
        title: "Дубль связки",
        status: 409,
        detail: "Связка для этого клиентского артикула уже существует",
        code: "CLIENT_SKU_MAPPING_EXISTS",
        requestId: "v2-fixture-client-sku-duplicate-001",
      },
    };
    const { requester } = requestSequence([{ error: problem }]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    await expect(
      repository.create({
        clientSku: "МОЙ-100",
        productId: mapping.productId,
      }),
    ).rejects.toMatchObject({
      name: "AppProblem",
      code: "CLIENT_SKU_MAPPING_EXISTS",
      status: 409,
      isProblemDetails: true,
      retryable: false,
    });
  });

  it("keeps malformed successful responses as contract errors", async () => {
    const { requester } = requestSequence([
      { body: { data: { clientSku: "МОЙ-100" }, meta: { requestId: "x" } } },
    ]);
    const repository = createClientSkuRepository(createApiV2Client(requester));

    await expect(repository.list()).rejects.toBeInstanceOf(ApiContractError);
  });
});
