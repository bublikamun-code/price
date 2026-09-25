import { nextTick } from 'vue'
import { createCartRepository } from '~/domain/cart/cart.repository'
import type { CartItemAdd, CartItemReplace } from '~/domain/api/v2/cart.schema'
import { AppProblem } from '~/domain/api/v2/problem'
import { useCartStore, type CartOwner } from '~/stores/cart'

export function useCartV2() {
  const auth = useAuth()
  const sessionContext = useSessionContext()
  const store = useCartStore()
  const repository = createCartRepository(useApiV2())

  function ownerFromContext(context: {
    user: { id: string }
    commercialScope: 'USER' | 'ORGANIZATION'
    organizationId: string | null
  }): CartOwner {
    return {
      userId: context.user.id,
      commercialScope: context.commercialScope,
      organizationId: context.organizationId,
    }
  }

  async function ensureLoaded(force = false) {
    const userId = auth.user?.id
    if (!userId) {
      store.reset()
      return null
    }

    const session = await sessionContext.ensureLoaded(force)
    if (!session || session.context.user.id !== userId) {
      store.reset()
      return null
    }
    // The context plugin invalidates cart state when the scope changes. Let
    // that watcher run before starting a new scoped request.
    await nextTick()
    return store.load(repository, ownerFromContext(session.context), force)
  }

  async function ensureMutationReady() {
    const snapshot = await ensureLoaded()
    if (!snapshot) {
      throw new AppProblem({
        code: 'AUTHENTICATION_REQUIRED',
        message: 'Не удалось определить коммерческий контекст',
        isProblemDetails: false,
        retryable: false,
      })
    }
    return snapshot
  }

  async function ensureReady() {
    await ensureMutationReady()
    await store.waitForIdle()
    return ensureLoaded(true)
  }

  async function addItem(payload: CartItemAdd) {
    await ensureMutationReady()
    return store.addItem(repository, payload)
  }

  async function replaceItem(productId: string, payload: CartItemReplace) {
    await ensureMutationReady()
    return store.replaceItem(repository, productId, payload)
  }

  async function removeItem(productId: string) {
    await ensureMutationReady()
    return store.removeItem(repository, productId)
  }

  async function clear() {
    await ensureMutationReady()
    return store.clear(repository)
  }

  return {
    store,
    ensureLoaded,
    ensureReady,
    refresh: () => ensureLoaded(true),
    addItem,
    replaceItem,
    removeItem,
    clear,
    reset: () => store.reset(),
  }
}
