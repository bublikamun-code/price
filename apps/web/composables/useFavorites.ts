// Избранное клиента (persist в БД). См. ARCHITECTURE_PLAN.md §19.
// Module-level ref — общий список SKU между каталогом, карточкой товара и страницей избранного.
// Ленивая загрузка: один запрос на сессию, ensureLoaded() дерётся из isFav/toggle.
import type { FavoriteListPage, FavoriteRead } from '~/types/api'

const PER_PAGE = 100

const items = ref<FavoriteRead[]>([])
const skus = ref<Set<string>>(new Set())
const loading = ref(false)
let loaded = false
let promised: Promise<void> | null = null

export function useFavorites() {
  const { request } = useApi()

  const count = computed(() => skus.value.size)

  function isFav(sku: string): boolean {
    void ensureLoaded()
    return skus.value.has(sku)
  }

  async function ensureLoaded(): Promise<void> {
    if (loaded) return
    if (!promised) {
      promised = (async () => {
        loading.value = true
        try {
          const res = await request<FavoriteListPage>('/api/v1/favorites', {
            query: { page: 1, per_page: PER_PAGE },
          })
          items.value = res.data
          skus.value = new Set(res.data.map(i => i.sku))
        } catch {
          // Тихо: избранное могло не загрузиться — сердечки будут пустыми.
          items.value = []
          skus.value = new Set()
        } finally {
          loading.value = false
          loaded = true
        }
      })()
    }
    return promised
  }

  // Принудительная перезагрузка (напр. после изменений на странице избранного).
  async function refresh(): Promise<void> {
    loaded = false
    promised = null
    await ensureLoaded()
  }

  async function remove(sku: string): Promise<void> {
    await request(`/api/v1/favorites/${encodeURIComponent(sku)}`, { method: 'DELETE' })
    const next = new Set(skus.value)
    next.delete(sku)
    skus.value = next
    items.value = items.value.filter(i => i.sku !== sku)
  }

  // Optimistic UI: состояние меняем синхронно, при ошибке — откат.
  // Возвращает итоговое состояние: true = в избранном.
  async function toggle(sku: string): Promise<boolean> {
    await ensureLoaded()
    const adding = !skus.value.has(sku)
    const next = new Set(skus.value)
    if (adding) next.add(sku)
    else next.delete(sku)
    skus.value = next
    if (!adding) items.value = items.value.filter(i => i.sku !== sku)
    try {
      if (adding) {
        await request('/api/v1/favorites', { method: 'POST', body: { sku } })
      } else {
        await request(`/api/v1/favorites/${encodeURIComponent(sku)}`, { method: 'DELETE' })
      }
    } catch (e) {
      const rollback = new Set(skus.value)
      if (adding) rollback.delete(sku)
      else rollback.add(sku)
      skus.value = rollback
      throw e
    }
    return adding
  }

  return { items, skus, count, loading, isFav, ensureLoaded, refresh, remove, toggle, init: ensureLoaded }
}
