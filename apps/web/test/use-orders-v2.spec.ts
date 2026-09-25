import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderDetail, OrderSummary } from "../domain/api/v2/order.schema";
import { useOrdersV2 } from "../composables/useOrdersV2";

const mocks = vi.hoisted(() => ({
  repository: {
    list: vi.fn(),
    getById: vi.fn(),
    create: vi.fn(),
    cancel: vi.fn(),
    repeat: vi.fn(),
  },
  refreshCart: vi.fn(async () => null),
  resetOrderStore: vi.fn(),
}));

vi.mock("../domain/order/order.repository", () => ({
  createOrderRepository: () => mocks.repository,
}));
vi.mock("../composables/useCartV2", () => ({
  useCartV2: () => ({ refresh: mocks.refreshCart }),
}));
vi.mock("../stores/orders", () => ({
  useOrdersStore: () => ({ reset: mocks.resetOrderStore }),
}));

const userId = "11111111-1111-4111-8111-111111111111";
const organizationId = "77777777-7777-4777-8777-777777777777";
const orderId = "88888888-8888-4888-8888-888888888888";
const baseContext: {
  user: { id: string };
  commercialScope: "USER" | "ORGANIZATION";
  organizationId: string | null;
} = {
  user: { id: userId },
  commercialScope: "USER",
  organizationId: null,
};

const money = { amount: "40.00", currency: "BYN" as const };
const summary: OrderSummary = {
  id: orderId,
  sequence: 8,
  organizationId: null,
  initiatedByUserId: userId,
  status: "NEW",
  total: money,
  exchangeRate: { value: "1.0000", scale: 4, source: "BYN" },
  createdAt: "2026-08-21T09:00:00Z",
  updatedAt: "2026-08-21T09:00:00Z",
  version: 3,
};
const detail: OrderDetail = {
  id: orderId,
  sequence: 8,
  organizationId: null,
  initiatedByUserId: userId,
  managerId: null,
  status: "NEW",
  total: money,
  exchangeRate: { value: "1.0000", scale: 4, source: "BYN" },
  lines: [],
  delivery: {
    method: "PICKUP",
    pickupPoint: null,
    addressId: null,
    address: null,
    contactName: null,
    phone: null,
    preferredDate: null,
    comment: null,
  },
  notes: null,
  createdAt: "2026-08-21T09:00:00Z",
  updatedAt: "2026-08-21T09:00:00Z",
  version: 3,
};

function installNuxtGlobals(context = baseContext) {
  Object.assign(globalThis, {
    useAuth: () => ({ user: { id: userId } }),
    useSessionContext: () => ({
      ensureLoaded: vi.fn(async () => ({ context, requestId: "session-1" })),
    }),
    useApiV2: () => ({ marker: "api-v2" }),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  installNuxtGlobals();
});

describe("client order UI v2 wiring", () => {
  it("lists with opaque cursor/status DTO parameters and no organization scope", async () => {
    mocks.repository.list.mockResolvedValue({
      orders: [summary],
      requestId: "orders-1",
      nextCursor: "cursor+/=",
      hasMore: true,
      limit: 10,
      sort: "createdAt,id",
    });
    const { list } = useOrdersV2();

    const result = await list({
      status: "IN_PROGRESS",
      limit: 10,
      cursor: "cursor+/=",
    });

    expect(result.nextCursor).toBe("cursor+/=");
    expect(mocks.repository.list).toHaveBeenCalledWith({
      status: "IN_PROGRESS",
      limit: 10,
      cursor: "cursor+/=",
    });
    expect(mocks.repository.list.mock.calls[0]?.[0]).not.toHaveProperty(
      "organizationId",
    );
  });

  it("reads and cancels strictly validated v2 DTO snapshots", async () => {
    mocks.repository.getById.mockResolvedValue({
      order: detail,
      requestId: "order-1",
    });
    const cancelled = { ...detail, status: "CANCELLED" as const, version: 4 };
    mocks.repository.cancel.mockResolvedValue({
      order: cancelled,
      requestId: "order-2",
    });
    const { getById, cancel } = useOrdersV2();

    await expect(getById(orderId)).resolves.toMatchObject({ order: detail });
    await expect(cancel(orderId)).resolves.toMatchObject({ order: cancelled });
    expect(mocks.repository.getById).toHaveBeenCalledWith(orderId);
    expect(mocks.repository.cancel).toHaveBeenCalledWith(orderId);
  });

  it("repeats with the v2 order version and refreshes the scoped cart", async () => {
    mocks.repository.repeat.mockResolvedValue({
      cart: {
        id: "cart-1",
        organizationId: null,
        version: 1,
        items: [],
        total: money,
        totalItems: 0,
      },
      etag: '"1"',
      requestId: "cart-1",
    });
    const { repeat } = useOrdersV2();

    await repeat(orderId, detail.version);

    expect(mocks.repository.repeat).toHaveBeenCalledWith(orderId, '"3"');
    expect(mocks.refreshCart).toHaveBeenCalledOnce();
  });

  it("rejects responses from a different server-resolved organization scope", async () => {
    installNuxtGlobals({
      ...baseContext,
      commercialScope: "ORGANIZATION",
      organizationId,
    });
    mocks.repository.getById.mockResolvedValue({
      order: detail,
      requestId: "order-1",
    });
    const { getById } = useOrdersV2();

    await expect(getById(orderId)).rejects.toMatchObject({
      code: "ORDER_SCOPE_MISMATCH",
      status: 409,
    });
  });
});
