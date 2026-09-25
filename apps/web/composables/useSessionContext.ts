import { createSessionRepository } from '~/domain/session/session.repository'
import { useSessionContextStore } from '~/stores/sessionContext'

export function useSessionContext() {
  const auth = useAuth()
  const store = useSessionContextStore()
  const repository = createSessionRepository(useApiV2())

  async function ensureLoaded(force = false) {
    const userId = auth.user?.id
    if (!userId) {
      store.clear()
      return null
    }
    return store.load(repository, userId, force)
  }

  function clear() {
    store.clear()
  }

  return {
    store,
    ensureLoaded,
    refresh: () => ensureLoaded(true),
    clear,
  }
}
