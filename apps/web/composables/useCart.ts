// Корзина клиента (persist в БД). См. ARCHITECTURE_PLAN.md §19.
// Module-level ref — общий счётчик между AppHeader и страницами.
import type { CartItemCreate, CartItemRead, CartItemUpdate, CartRead } from '~/types/api'

const cart = ref<CartRead | null>(null)
const loading = ref(false)
// Последняя добавленная позиция — триггер всплывающей корзины (снизу справа).
const lastAdded = ref<CartItemRead | null>(null)

export function useCart() {
  const { request } = useApi()

  const count = computed(() => cart.value?.total_items ?? 0)
  const data = computed(() => cart.value)

  async function refresh(): Promise<CartRead | null> {
    loading.value = true
    try {
      cart.value = await request<CartRead>('/api/v1/cart')
    } catch {
      // Тихо: корзина могла не инициализироваться; AppHeader покажет 0.
      cart.value = null
    } finally {
      loading.value = false
    }
    return cart.value
  }

  async function add(payload: CartItemCreate): Promise<CartRead> {
    cart.value = await request<CartRead>('/api/v1/cart/items', {
      method: 'POST',
      body: payload,
    })
    lastAdded.value = cart.value.items.find(i => i.sku === payload.sku) ?? null
    return cart.value
  }

  async function update(sku: string, payload: CartItemUpdate): Promise<CartRead> {
    cart.value = await request<CartRead>(`/api/v1/cart/items/${encodeURIComponent(sku)}`, {
      method: 'PUT',
      body: payload,
    })
    return cart.value
  }

  async function remove(sku: string): Promise<CartRead> {
    cart.value = await request<CartRead>(`/api/v1/cart/items/${encodeURIComponent(sku)}`, {
      method: 'DELETE',
    })
    return cart.value
  }

  async function clear(): Promise<CartRead> {
    cart.value = await request<CartRead>('/api/v1/cart', { method: 'DELETE' })
    return cart.value
  }

  return { cart, data, count, loading, lastAdded, refresh, add, update, remove, clear }
}
