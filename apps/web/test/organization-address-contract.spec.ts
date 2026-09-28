import { describe, expect, it } from "vitest";
import type { FetchOptions } from "ofetch";

import {
  ApiContractError,
  createApiV2Client,
  type ApiRequester,
} from "../domain/api/v2/client";
import {
  organizationAddressCreateSchema,
  organizationAddressListResponseSchema,
  organizationAddressResponseSchema,
  type OrganizationAddressCreate,
} from "../domain/api/v2/organizations.schema";
import { orderDeliveryCreateSchema } from "../domain/api/v2/order.schema";
import { createOrganizationRepository } from "../domain/organization/organization.repository";

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

const addressId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const address = {
  id: addressId,
  kind: "DELIVERY",
  label: "Склад",
  recipientName: "Иван Иванов",
  phone: "+375 29 000-00-00",
  addressLine: "ул. Притыцкого, 12",
  city: "Минск",
  postalCode: "220004",
  countryCode: "BY",
  isDefault: true,
  createdAt: "2026-09-28T10:00:00Z",
};
const listResponse = {
  data: [address],
  meta: { requestId: "v2-fixture-address-list-001" },
};
const createResponse = {
  data: address,
  meta: { requestId: "v2-fixture-address-create-001" },
};
const createPayload: OrganizationAddressCreate = {
  kind: "DELIVERY",
  addressLine: "  ул. Притыцкого, 12  ",
  label: "Склад",
  recipientName: "Иван Иванов",
  phone: "+375 29 000-00-00",
  city: "Минск",
  isDefault: false,
};

describe("API v2 organization address contract", () => {
  it("validates the strict camelCase list and single address envelopes", () => {
    const list = organizationAddressListResponseSchema.parse(listResponse);
    expect(list.data[0]).toMatchObject({
      id: addressId,
      kind: "DELIVERY",
      addressLine: "ул. Притыцкого, 12",
      countryCode: "BY",
      isDefault: true,
    });
    expect(organizationAddressResponseSchema.parse(createResponse).data.kind).toBe(
      "DELIVERY",
    );

    const snake = structuredClone(listResponse);
    snake.data[0] = { ...address, address_line: address.addressLine } as typeof snake.data[number];
    delete (snake.data[0] as Record<string, unknown>).addressLine;
    expect(organizationAddressListResponseSchema.safeParse(snake).success).toBe(
      false,
    );
  });

  it("lists addresses from the me-organization endpoint without extra headers", async () => {
    const { requester, requests } = requestSequence([{ body: listResponse }]);
    const repository = createOrganizationRepository(createApiV2Client(requester));

    const result = await repository.listAddresses();

    expect(result.addresses).toHaveLength(1);
    expect(result.requestId).toBe("v2-fixture-address-list-001");
    expect(requests[0]?.url).toBe("/api/v2/me/organization/addresses");
    expect(requests[0]?.options.method).toBe("GET");
    expect(requests[0]?.options.body).toBeUndefined();
    expect(requests[0]?.options.headers).toBeUndefined();
  });

  it("creates an address with Idempotency-Key and a normalized camelCase body", async () => {
    const { requester, requests } = requestSequence([{ body: createResponse }]);
    const repository = createOrganizationRepository(createApiV2Client(requester));

    const result = await repository.createAddress(createPayload, "address-create-1");

    expect(result.address.id).toBe(addressId);
    expect(result.requestId).toBe("v2-fixture-address-create-001");
    expect(requests[0]?.url).toBe("/api/v2/me/organization/addresses");
    expect(requests[0]?.options.method).toBe("POST");
    expect(requests[0]?.options.headers).toMatchObject({
      "Idempotency-Key": "address-create-1",
    });
    expect(requests[0]?.options.body).toMatchObject({
      kind: "DELIVERY",
      addressLine: "ул. Притыцкого, 12",
      city: "Минск",
      isDefault: false,
    });
    expect(JSON.stringify(requests[0]?.options.body)).not.toContain("address_line");
  });

  it("rejects malformed create payloads before issuing a request", async () => {
    const { requester, requests } = requestSequence([]);
    const repository = createOrganizationRepository(createApiV2Client(requester));

    expect(
      organizationAddressCreateSchema.safeParse({ ...createPayload, kind: "SHIPPING" })
        .success,
    ).toBe(false);
    expect(
      organizationAddressCreateSchema.safeParse({
        ...createPayload,
        addressLine: "x".repeat(501),
      }).success,
    ).toBe(false);
    expect(
      organizationAddressCreateSchema.safeParse({
        ...createPayload,
        addressLine: "   ",
      }).success,
    ).toBe(false);
    expect(
      organizationAddressCreateSchema.safeParse({ ...createPayload, countryCode: "by" })
        .success,
    ).toBe(false);
    expect(
      organizationAddressCreateSchema.safeParse({ ...createPayload, extra: true })
        .success,
    ).toBe(false);

    await expect(
      repository.createAddress(
        { ...createPayload, address_line: "ул. Притыцкого, 12" } as never,
        "address-create-1",
      ),
    ).rejects.toBeTruthy();
    expect(requests).toHaveLength(0);
  });

  it("maps the address duplicate conflict to an AppProblem without retry", async () => {
    const problem = {
      data: {
        type: "https://priceweb.local/problems/address-duplicate",
        title: "Дубль адреса",
        status: 409,
        detail: "Адрес с таким kind и addressLine уже существует",
        code: "ADDRESS_DUPLICATE",
        requestId: "v2-fixture-address-duplicate-001",
      },
    };
    const { requester } = requestSequence([{ error: problem }]);
    const repository = createOrganizationRepository(createApiV2Client(requester));

    await expect(
      repository.createAddress(createPayload, "address-create-1"),
    ).rejects.toMatchObject({
      name: "AppProblem",
      code: "ADDRESS_DUPLICATE",
      status: 409,
      requestId: "v2-fixture-address-duplicate-001",
      isProblemDetails: true,
      retryable: false,
    });
  });

  it("keeps malformed successful responses as contract errors", async () => {
    const { requester } = requestSequence([
      { body: { data: { kind: "DELIVERY" }, meta: { requestId: "x" } } },
    ]);
    const repository = createOrganizationRepository(createApiV2Client(requester));

    await expect(repository.listAddresses()).rejects.toBeInstanceOf(ApiContractError);
  });

  it("accepts addressId in the order delivery create and rejects legacy spellings", () => {
    expect(
      orderDeliveryCreateSchema.safeParse({
        method: "DELIVERY",
        addressId: addressId,
        contactName: "Иван Иванов",
        phone: "+375 29 000-00-00",
      }).success,
    ).toBe(true);
    expect(
      orderDeliveryCreateSchema.safeParse({
        method: "DELIVERY",
        address_id: addressId,
      }).success,
    ).toBe(false);
    expect(
      orderDeliveryCreateSchema.safeParse({
        method: "DELIVERY",
        addressId: "not-a-uuid",
      }).success,
    ).toBe(false);
    expect(
      orderDeliveryCreateSchema.safeParse({
        method: "DELIVERY",
        addressId: addressId,
        freeTextAddress: "ул. Притыцкого, 12",
      }).success,
    ).toBe(false);
  });
});
