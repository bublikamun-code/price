import { defineStore } from 'pinia'
import { ref } from 'vue'
import { AppProblem, toAppProblem } from '../domain/api/v2/problem'
import type { OrderCreate } from '../domain/api/v2/order.schema'
import type { OrderCreateResult, OrderRepository } from '../domain/order/order.repository'

export interface OrderOwner {
  userId: string
  commercialScope: 'USER' | 'ORGANIZATION'
  organizationId: string | null
}

function ownerKey(owner: OrderOwner): string {
  return `${owner.userId}|${owner.commercialScope}|${owner.organizationId ?? 'USER'}`
}

function scopeMismatch(): AppProblem {
  return new AppProblem({
    code: 'ORDER_SCOPE_MISMATCH',
    status: 409,
    message: 'Ответ заявки не соответствует активному коммерческому контексту',
    isProblemDetails: false,
    retryable: false,
  })
}

function ownerChanged(): AppProblem {
  return new AppProblem({
    code: 'ORDER_OWNER_CHANGED',
    message: 'Коммерческий контекст изменился во время создания заявки',
    isProblemDetails: false,
    retryable: false,
  })
}

function stableFingerprint(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'undefined'
  if (Array.isArray(value)) return `[${value.map(stableFingerprint).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableFingerprint(record[key])}`)
    .join(',')}}`
}

function createIdempotencyKey(): string {
  return globalThis.crypto.randomUUID()
}

export const useOrdersStore = defineStore('orders-v2', () => {
  const order = ref<OrderCreateResult['order'] | null>(null)
  const requestId = ref<string | null>(null)
  const owner = ref<OrderOwner | null>(null)
  const loading = ref(false)
  const error = ref<AppProblem | null>(null)
  const cartRefreshError = ref<AppProblem | null>(null)
  const idempotencyKey = ref<string | null>(null)
  const pendingFingerprint = ref<string | null>(null)
  const lastFingerprint = ref<string | null>(null)
  const result = ref<OrderCreateResult | null>(null)

  let generation = 0
  let submitQueue: Promise<unknown> = Promise.resolve()

  function reset() {
    generation += 1
    submitQueue = Promise.resolve()
    owner.value = null
    order.value = null
    requestId.value = null
    loading.value = false
    error.value = null
    cartRefreshError.value = null
    idempotencyKey.value = null
    pendingFingerprint.value = null
    lastFingerprint.value = null
    result.value = null
  }

  function resetForOwner(nextOwner: OrderOwner) {
    if (owner.value && ownerKey(owner.value) === ownerKey(nextOwner)) return
    reset()
    owner.value = nextOwner
  }

  function isCurrent(requestGeneration: number, requestOwnerKey: string) {
    return (
      owner.value !== null &&
      generation === requestGeneration &&
      ownerKey(owner.value) === requestOwnerKey
    )
  }

  function validateScope(resultValue: OrderCreateResult, expected: OrderOwner) {
    const organizationMatches =
      expected.commercialScope === 'USER'
        ? resultValue.order.organizationId === null
        : resultValue.order.organizationId === expected.organizationId
    if (!organizationMatches || resultValue.order.initiatedByUserId !== expected.userId) {
      throw scopeMismatch()
    }
  }

  function enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const queued = submitQueue.then(operation, operation)
    submitQueue = queued.then(
      () => undefined,
      () => undefined,
    )
    return queued
  }

  async function submit(
    repository: OrderRepository,
    nextOwner: OrderOwner,
    payload: OrderCreate,
  ): Promise<OrderCreateResult> {
    const nextKey = ownerKey(nextOwner)
    if (!owner.value || ownerKey(owner.value) !== nextKey) resetForOwner(nextOwner)

    const fingerprint = stableFingerprint(payload)
    const requestGeneration = generation
    return enqueue(async () => {
      if (lastFingerprint.value === fingerprint && result.value) return result.value
      if (!isCurrent(requestGeneration, nextKey)) throw ownerChanged()

      if (lastFingerprint.value !== fingerprint) {
        result.value = null
        order.value = null
        requestId.value = null
      }
      if (pendingFingerprint.value !== fingerprint || !idempotencyKey.value) {
        pendingFingerprint.value = fingerprint
        idempotencyKey.value = createIdempotencyKey()
      }

      const requestOwnerKey = ownerKey(owner.value!)
      const key = idempotencyKey.value
      loading.value = true
      error.value = null
      cartRefreshError.value = null
      try {
        const submitted = await repository.create(payload, key)
        if (!isCurrent(requestGeneration, requestOwnerKey)) throw ownerChanged()
        validateScope(submitted, owner.value!)
        result.value = submitted
        order.value = submitted.order
        requestId.value = submitted.requestId
        lastFingerprint.value = fingerprint
        pendingFingerprint.value = null
        idempotencyKey.value = null
        return result.value!
      } catch (cause) {
        if (!isCurrent(requestGeneration, requestOwnerKey)) throw ownerChanged()
        const problem = toAppProblem(cause, 'Не удалось создать заявку')
        error.value = problem
        if (problem.code === 'IDEMPOTENCY_KEY_REUSED') {
          pendingFingerprint.value = null
          idempotencyKey.value = null
        }
        throw problem
      } finally {
        if (isCurrent(requestGeneration, requestOwnerKey)) loading.value = false
      }
    })
  }

  function setCartRefreshError(cause: unknown) {
    cartRefreshError.value = toAppProblem(cause, 'Заявка создана, но корзину не удалось обновить')
  }

  return {
    order,
    requestId,
    owner,
    loading,
    error,
    cartRefreshError,
    idempotencyKey,
    result,
    reset,
    setCartRefreshError,
    submit,
  }
})
