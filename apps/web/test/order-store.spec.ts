import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import type { OrderCreate } from "../domain/api/v2/order.schema";
import type {
  OrderCreateResult,
  OrderRepository,
} from "../domain/order/order.repository";
import { useOrdersStore, type OrderOwner } from "../stores/orders";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = (name: string) =>
  JSON.parse(
    readFileSync(resolve(webRoot, "../api/tests/fixtures/v2", name), "utf8"),
  );

const userOwner: OrderOwner = {
  userId: "11111111-1111-4111-8111-111111111111",
  commercialScope: "USER",
  organizationId: null,
};
const orgOwner: OrderOwner = {
  userId: "11111111-1111-4111-8111-111111111111",
  commercialScope: "ORGANIZATION",
  organizationId: "77777777-7777-4777-8777-777777777777",
};

function payload(): OrderCreate {
  return fixture("order_create_request.json") as OrderCreate;
}

function result(organizationId: string | null = null): OrderCreateResult {
  const body = fixture("order_create_success.json");
  body.data.organizationId = organizationId;
  return {
    order: body.data,
    requestId: body.meta.requestId,
    idempotencyReplayed: false,
  };
}

function repositoryMock(
  overrides: Partial<OrderRepository> = {},
): OrderRepository {
  return {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(async () => result()),
    cancel: vi.fn(),
    repeat: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("request-scoped v2 order store", () => {
  it("creates once for repeated submits of the same payload", async () => {
    const repository = repositoryMock();
    const store = useOrdersStore();
    const orderPayload = payload();

    const first = await store.submit(repository, userOwner, orderPayload);
    const second = await store.submit(repository, userOwner, orderPayload);

    expect(first.order.id).toBe("88888888-8888-4888-8888-888888888888");
    expect(second).toBe(first);
    expect(repository.create).toHaveBeenCalledTimes(1);
    expect(store.idempotencyKey).toBeNull();
  });

  it("retains the same key after a transport failure and rotates it when payload changes", async () => {
    const repository = repositoryMock({
      create: vi
        .fn()
        .mockRejectedValueOnce(new Error("network unavailable"))
        .mockResolvedValueOnce(result()),
    });
    const store = useOrdersStore();
    const firstPayload = payload();
    const changedPayload = {
      ...firstPayload,
      items: [{ ...firstPayload.items[0]!, quantity: "7" }],
    };

    await expect(
      store.submit(repository, userOwner, firstPayload),
    ).rejects.toMatchObject({
      retryable: true,
    });
    await store.submit(repository, userOwner, firstPayload);
    const firstKey = (repository.create as ReturnType<typeof vi.fn>).mock
      .calls[0]?.[1];

    await expect(
      store.submit(repository, userOwner, changedPayload),
    ).rejects.toMatchObject({
      retryable: true,
    });
    const secondKey = (repository.create as ReturnType<typeof vi.fn>).mock
      .calls[2]?.[1];
    expect(firstKey).toBeTruthy();
    expect(secondKey).not.toBe(firstKey);
  });

  it("serializes double submit and keeps the first result", async () => {
    let resolveCreate: ((value: OrderCreateResult) => void) | undefined;
    const firstCreate = new Promise<OrderCreateResult>((resolve) => {
      resolveCreate = resolve;
    });
    const repository = repositoryMock({
      create: vi.fn().mockReturnValue(firstCreate),
    });
    const store = useOrdersStore();
    const orderPayload = payload();

    const first = store.submit(repository, userOwner, orderPayload);
    const second = store.submit(repository, userOwner, orderPayload);
    await Promise.resolve();
    expect(repository.create).toHaveBeenCalledTimes(1);
    resolveCreate?.(result());
    const [firstResult, secondResult] = await Promise.all([first, second]);

    expect(firstResult).toBe(secondResult);
    expect(repository.create).toHaveBeenCalledTimes(1);
  });

  it("rejects a response from a different organization scope", async () => {
    const repository = repositoryMock({
      create: vi.fn(async () => result(null)),
    });
    const store = useOrdersStore();

    await expect(
      store.submit(repository, orgOwner, payload()),
    ).rejects.toMatchObject({
      code: "ORDER_SCOPE_MISMATCH",
      status: 409,
    });
    expect(store.order).toBeNull();
  });

  it("drops a delayed response after owner invalidation", async () => {
    let resolveCreate: ((value: OrderCreateResult) => void) | undefined;
    const pending = new Promise<OrderCreateResult>((resolve) => {
      resolveCreate = resolve;
    });
    const repository = repositoryMock({
      create: vi.fn().mockReturnValue(pending),
    });
    const store = useOrdersStore();

    const submission = store.submit(repository, userOwner, payload());
    store.reset();
    resolveCreate?.(result());

    await expect(submission).rejects.toMatchObject({
      code: "ORDER_OWNER_CHANGED",
    });
    expect(store.order).toBeNull();
  });
});
