import { defineStore } from 'pinia'
import { ref } from 'vue'
import { toAppProblem, type AppProblem } from '../domain/api/v2/problem'
import type { SessionContext } from '../domain/api/v2/session.schema'
import type { SessionRepository, SessionSnapshot } from '../domain/session/session.repository'

export const useSessionContextStore = defineStore('session-context', () => {
  const context = ref<SessionContext | null>(null)
  const requestId = ref<string | null>(null)
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<AppProblem | null>(null)
  const ownerUserId = ref<string | null>(null)

  let generation = 0
  let inFlight: Promise<SessionSnapshot> | null = null
  let inFlightOwnerId: string | null = null

  function resetForOwner(userId: string) {
    generation += 1
    inFlight = null
    inFlightOwnerId = null
    ownerUserId.value = userId
    context.value = null
    requestId.value = null
    loaded.value = false
    error.value = null
    loading.value = false
  }

  function clear() {
    generation += 1
    inFlight = null
    inFlightOwnerId = null
    ownerUserId.value = null
    context.value = null
    requestId.value = null
    loading.value = false
    loaded.value = false
    error.value = null
  }

  async function load(
    repository: SessionRepository,
    userId: string,
    force = false,
  ): Promise<SessionSnapshot | null> {
    if (ownerUserId.value !== userId) resetForOwner(userId)
    if (!force && loaded.value && context.value) {
      return { context: context.value, requestId: requestId.value ?? '' }
    }
    if (inFlight && inFlightOwnerId === userId) return inFlight

    const requestGeneration = generation
    loading.value = true
    error.value = null
    const request = repository.getCurrent()
    inFlight = request
    inFlightOwnerId = userId

    try {
      const snapshot = await request
      if (requestGeneration !== generation || ownerUserId.value !== userId) return snapshot
      context.value = snapshot.context
      requestId.value = snapshot.requestId
      loaded.value = true
      return snapshot
    } catch (cause) {
      if (requestGeneration !== generation || ownerUserId.value !== userId) return null
      error.value = toAppProblem(cause, 'Не удалось загрузить контекст организации')
      throw error.value
    } finally {
      if (inFlight === request) {
        inFlight = null
        inFlightOwnerId = null
        loading.value = false
      }
    }
  }

  return {
    context,
    requestId,
    loading,
    loaded,
    error,
    ownerUserId,
    clear,
    load,
  }
})
