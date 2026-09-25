import { watch } from 'vue'
import { useCartStore } from '~/stores/cart'
import { useOrdersStore } from '~/stores/orders'
import { useSessionContextStore } from '~/stores/sessionContext'

export default defineNuxtPlugin(() => {
  const auth = useAuth()
  const sessionStore = useSessionContextStore()
  const cartStore = useCartStore()
  const orderStore = useOrdersStore()
  let previousUserId = auth.user?.id ?? null
  let previousScopeKey: string | null = null

  watch(
    () => auth.user?.id ?? null,
    (userId) => {
      if (userId === previousUserId) return
      previousUserId = userId
      sessionStore.clear()
      cartStore.reset()
      orderStore.reset()
    },
  )

  watch(
    () => {
      const context = sessionStore.context
      if (!context) return null
      return `${context.commercialScope}|${context.organizationId ?? 'USER'}`
    },
    (scopeKey) => {
      if (scopeKey === previousScopeKey) return
      previousScopeKey = scopeKey
      cartStore.reset()
      orderStore.reset()
    },
  )
})
