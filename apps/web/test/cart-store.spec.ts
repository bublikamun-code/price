import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { AppProblem } from '../domain/api/v2/problem'
import type { CartRepository, CartSnapshot } from '../domain/cart/cart.repository'
import { useCartStore, type CartOwner } from '../stores/cart'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cartFixture = () =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2/cart_get_success.json'), 'utf8'))

const userOwner: CartOwner = {
  userId: 'user-1',
  commercialScope: 'USER',
  organizationId: null,
}
const orgOwner: CartOwner = {
  userId: 'user-1',
  commercialScope: 'ORGANIZATION',
  organizationId: '77777777-7777-4777-8777-777777777777',
}

function snapshot(version = 4, organizationId: string | null = orgOwner.organizationId): CartSnapshot {
  const body = cartFixture()
  body.data.version = version
  body.data.organizationId = organizationId
  return {
    cart: body.data,
    etag: `"${version}"`,
    requestId: body.meta.requestId,
  }
}

function repositoryMock(overrides: Partial<CartRepository> = {}): CartRepository {
  return {
    getCurrent: vi.fn(async () => snapshot()),
    addItem: vi.fn(async () => snapshot(5)),
    replaceItem: vi.fn(async () => snapshot(6)),
    removeItem: vi.fn(async () => snapshot(7)),
    clear: vi.fn(async () => snapshot(8)),
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('request-scoped v2 cart store', () => {
  it('loads one scoped cart and uses its ETag for the next mutation', async () => {
    const repository = repositoryMock()
    const store = useCartStore()

    await store.load(repository, orgOwner)
    await store.addItem(repository, {
      productId: '66666666-6666-4666-8666-666666666666',
      quantity: '2',
    })

    expect(store.cart?.version).toBe(5)
    expect(store.etag).toBe('"5"')
    expect(repository.getCurrent).toHaveBeenCalledTimes(1)
    expect(repository.addItem).toHaveBeenCalledWith(
      { productId: '66666666-6666-4666-8666-666666666666', quantity: '2' },
      '"4"',
    )
    expect(store.lastAddedProductId).toBe('66666666-6666-4666-8666-666666666666')
  })

  it('does not mix USER and ORGANIZATION carts', async () => {
    const repository = repositoryMock({
      getCurrent: vi
        .fn()
        .mockResolvedValueOnce(snapshot(4, null))
        .mockResolvedValueOnce(snapshot(4, orgOwner.organizationId)),
    })
    const store = useCartStore()

    await store.load(repository, userOwner)
    expect(store.cart?.organizationId).toBeNull()

    await store.load(repository, orgOwner)
    expect(store.cart?.organizationId).toBe(orgOwner.organizationId)
    expect(store.owner).toEqual(orgOwner)
  })

  it('drops a delayed response after owner invalidation', async () => {
    let resolveFirst: ((value: CartSnapshot) => void) | undefined
    const first = new Promise<CartSnapshot>((resolve) => {
      resolveFirst = resolve
    })
    const repository = repositoryMock({
      getCurrent: vi
        .fn()
        .mockReturnValueOnce(first)
        .mockResolvedValueOnce(snapshot(9, orgOwner.organizationId)),
    })
    const store = useCartStore()

    const firstLoad = store.load(repository, userOwner)
    await store.load(repository, orgOwner)
    resolveFirst?.(snapshot(4, null))
    await firstLoad

    expect(store.cart?.version).toBe(9)
    expect(store.cart?.organizationId).toBe(orgOwner.organizationId)
  })

  it('refetches on stale version without replaying the mutation', async () => {
    const stale = new AppProblem({
      code: 'STALE_RESOURCE_VERSION',
      status: 409,
      message: 'Корзина уже изменена',
      isProblemDetails: true,
      retryable: false,
    })
    const repository = repositoryMock({
      getCurrent: vi
        .fn()
        .mockResolvedValueOnce(snapshot(4))
        .mockResolvedValueOnce(snapshot(5)),
      addItem: vi.fn().mockRejectedValue(stale),
    })
    const store = useCartStore()
    await store.load(repository, orgOwner)

    await expect(
      store.addItem(repository, {
        productId: '66666666-6666-4666-8666-666666666666',
        quantity: '1',
      }),
    ).rejects.toMatchObject({ code: 'STALE_RESOURCE_VERSION' })

    expect(store.cart?.version).toBe(5)
    expect(store.conflict).toBe(true)
    expect(store.error?.code).toBe('STALE_RESOURCE_VERSION')
    expect(repository.addItem).toHaveBeenCalledTimes(1)
    expect(repository.getCurrent).toHaveBeenCalledTimes(2)
  })

  it('rejects a response whose organization does not match the owner', async () => {
    const repository = repositoryMock({
      getCurrent: vi.fn().mockResolvedValue(snapshot(4, null)),
    })
    const store = useCartStore()

    await expect(store.load(repository, orgOwner)).rejects.toMatchObject({
      code: 'CART_SCOPE_MISMATCH',
    })
    expect(store.cart).toBeNull()
  })
})
