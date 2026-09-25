import { defineStore } from 'pinia'
import { ref } from 'vue'
import { AppProblem, toAppProblem } from '../domain/api/v2/problem'
import type {
  CartItemAdd,
  CartItemReplace,
  CartSummary,
} from '../domain/api/v2/cart.schema'
import type { CartRepository, CartSnapshot } from '../domain/cart/cart.repository'

export interface CartOwner {
  userId: string
  commercialScope: 'USER' | 'ORGANIZATION'
  organizationId: string | null
}

function ownerKey(owner: CartOwner): string {
  return `${owner.userId}|${owner.commercialScope}|${owner.organizationId ?? 'USER'}`
}

function scopeMismatch(): AppProblem {
  return new AppProblem({
    code: 'CART_SCOPE_MISMATCH',
    status: 409,
    message: 'Ответ корзины не соответствует активному коммерческому контексту',
    isProblemDetails: false,
    retryable: false,
  })
}

function invalidatedOwner(): AppProblem {
  return new AppProblem({
    code: 'CART_OWNER_CHANGED',
    message: 'Коммерческий контекст изменился во время операции',
    isProblemDetails: false,
    retryable: false,
  })
}

export const useCartStore = defineStore('cart-v2', () => {
  const cart = ref<CartSummary | null>(null)
  const etag = ref<string | null>(null)
  const requestId = ref<string | null>(null)
  const owner = ref<CartOwner | null>(null)
  const loading = ref(false)
  const loaded = ref(false)
  const saving = ref(false)
  const error = ref<AppProblem | null>(null)
  const conflict = ref(false)
  const lastAddedProductId = ref<string | null>(null)

  let generation = 0
  let inFlight: Promise<CartSnapshot> | null = null
  let inFlightOwnerKey: string | null = null
  let mutationQueue: Promise<unknown> = Promise.resolve()

  function reset() {
    generation += 1
    inFlight = null
    inFlightOwnerKey = null
    mutationQueue = Promise.resolve()
    owner.value = null
    cart.value = null
    etag.value = null
    requestId.value = null
    loading.value = false
    loaded.value = false
    saving.value = false
    error.value = null
    conflict.value = false
    lastAddedProductId.value = null
  }

  function resetForOwner(nextOwner: CartOwner) {
    const nextKey = ownerKey(nextOwner)
    if (owner.value && ownerKey(owner.value) === nextKey) return
    reset()
    owner.value = nextOwner
  }

  function isCurrent(requestGeneration: number, requestOwnerKey: string) {
    if (!owner.value) return false
    return generation === requestGeneration && ownerKey(owner.value) === requestOwnerKey
  }

  function validateScope(snapshot: CartSnapshot, expected: CartOwner) {
    if (expected.commercialScope === 'USER' && snapshot.cart.organizationId !== null) {
      throw scopeMismatch()
    }
    if (
      expected.commercialScope === 'ORGANIZATION' &&
      snapshot.cart.organizationId !== expected.organizationId
    ) {
      throw scopeMismatch()
    }
  }

  function applySnapshot(snapshot: CartSnapshot) {
    cart.value = snapshot.cart
    etag.value = snapshot.etag
    requestId.value = snapshot.requestId
    loaded.value = true
    error.value = null
    conflict.value = false
  }

  async function load(
    repository: CartRepository,
    nextOwner: CartOwner,
    force = false,
  ): Promise<CartSnapshot | null> {
    const nextKey = ownerKey(nextOwner)
    if (!owner.value || ownerKey(owner.value) !== nextKey) {
      resetForOwner(nextOwner)
    }
    if (!force && loaded.value && cart.value && etag.value) {
      return { cart: cart.value, etag: etag.value, requestId: requestId.value ?? '' }
    }
    if (inFlight && inFlightOwnerKey === nextKey) return inFlight

    const requestGeneration = generation
    loading.value = true
    error.value = null
    const request = repository.getCurrent()
    inFlight = request
    inFlightOwnerKey = nextKey

    try {
      const snapshot = await request
      if (!isCurrent(requestGeneration, nextKey)) return snapshot
      validateScope(snapshot, nextOwner)
      applySnapshot(snapshot)
      return snapshot
    } catch (cause) {
      if (!isCurrent(requestGeneration, nextKey)) return null
      error.value = toAppProblem(cause, 'Не удалось загрузить корзину')
      throw error.value
    } finally {
      if (inFlight === request) {
        inFlight = null
        inFlightOwnerKey = null
        loading.value = false
      }
    }
  }

  async function waitForIdle(): Promise<void> {
    await mutationQueue
  }

  function enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = mutationQueue.then(operation, operation)
    mutationQueue = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }

  async function mutate(
    repository: CartRepository,
    operation: (ifMatch: string) => Promise<CartSnapshot>,
  ): Promise<CartSnapshot> {
    if (!owner.value) throw invalidatedOwner()
    const requestGeneration = generation
    const requestOwnerKey = ownerKey(owner.value)
    const currentOwner = owner.value

    return enqueue(async () => {
      if (!isCurrent(requestGeneration, requestOwnerKey)) throw invalidatedOwner()
      if (!etag.value) throw invalidatedOwner()
      saving.value = true
      try {
        const snapshot = await operation(etag.value)
        if (!isCurrent(requestGeneration, requestOwnerKey)) return snapshot
        validateScope(snapshot, currentOwner)
        applySnapshot(snapshot)
        return snapshot
      } catch (cause) {
        if (!isCurrent(requestGeneration, requestOwnerKey)) throw invalidatedOwner()
        const problem = toAppProblem(cause, 'Не удалось изменить корзину')
        error.value = problem
        if (problem.code === 'STALE_RESOURCE_VERSION') {
          conflict.value = true
          try {
            await load(repository, currentOwner, true)
          } catch {
            // Keep the original conflict visible when the refetch also fails.
          }
          conflict.value = true
          error.value = problem
        }
        throw problem
      } finally {
        if (isCurrent(requestGeneration, requestOwnerKey)) saving.value = false
      }
    })
  }

  function addItem(repository: CartRepository, payload: CartItemAdd) {
    const mutationOwner = owner.value
    return mutate(repository, (ifMatch) => repository.addItem(payload, ifMatch)).then((snapshot) => {
      if (owner.value === mutationOwner) lastAddedProductId.value = payload.productId
      return snapshot
    })
  }

  function replaceItem(
    repository: CartRepository,
    productId: string,
    payload: CartItemReplace,
  ) {
    return mutate(repository, (ifMatch) => repository.replaceItem(productId, payload, ifMatch))
  }

  function removeItem(repository: CartRepository, productId: string) {
    return mutate(repository, (ifMatch) => repository.removeItem(productId, ifMatch))
  }

  function clear(repository: CartRepository) {
    return mutate(repository, (ifMatch) => repository.clear(ifMatch))
  }

  return {
    cart,
    etag,
    requestId,
    owner,
    loading,
    loaded,
    saving,
    error,
    conflict,
    lastAddedProductId,
    reset,
    load,
    waitForIdle,
    addItem,
    replaceItem,
    removeItem,
    clear,
  }
})
