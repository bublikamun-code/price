// Мгновенный поиск (typeahead) — см. .output.bak AppHeader
interface TypeaheadProduct {
  id: string
  sku: string
  name: string
  photo_key: string | null
  brand?: { name: string }
  retail_price: number
  client_price: number
  currency: string
  has_discount: boolean
  stock_status: string
}

interface UseSearchTypeaheadOptions {
  minLen?: number
  debounceMs?: number
  perPage?: number
}

export function useSearchTypeahead(opts: UseSearchTypeaheadOptions = {}) {
  const { request } = useApi()

  const query = ref('')
  const results = ref<TypeaheadProduct[]>([])
  const loading = ref(false)
  const open = ref(false)
  const active = ref(-1)

  let timer: ReturnType<typeof setTimeout> | null = null
  let seq = 0

  const minLen = opts.minLen ?? 2
  const debounceMs = opts.debounceMs ?? 300
  const perPage = opts.perPage ?? 6

  function close() {
    open.value = false
    active.value = -1
    loading.value = false
  }

  function clear() {
    query.value = ''
    results.value = []
    close()
  }

  function displayPrice(p: TypeaheadProduct): number {
    return p.has_discount ? p.client_price : p.retail_price
  }

  async function fetchResults() {
    const q = query.value.trim()
    if (q.length < minLen) {
      close()
      return
    }

    const s = ++seq
    loading.value = true
    open.value = true

    try {
      const res = await request<{ data: TypeaheadProduct[] }>('/api/v1/catalog/products', {
        query: { q, page: 1, per_page: perPage },
      })
      if (s !== seq) return
      results.value = res.data as unknown as TypeaheadProduct[]
      active.value = -1
      open.value = true
    } catch {
      if (s === seq) close()
    } finally {
      if (s === seq) loading.value = false
    }
  }

  function onInput() {
    if (timer) clearTimeout(timer)
    const q = query.value.trim()
    if (q.length < minLen) {
      close()
      return
    }
    timer = setTimeout(fetchResults, debounceMs)
  }

  function goProduct(p: TypeaheadProduct) {
    clear()
    navigateTo(`/catalog/${p.sku}`)
  }

  function goCatalog() {
    const q = query.value.trim()
    clear()
    if (!q) {
      navigateTo({ path: '/catalog', query: {} })
      return
    }
    const exact = results.value.find(p => p.sku === q)
    if (exact) {
      navigateTo(`/catalog/${exact.sku}`)
    } else {
      navigateTo({ path: '/catalog', query: { q } })
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open.value || !results.value.length) {
      if (e.key === 'Enter') {
        e.preventDefault()
        goCatalog()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        clear()
      }
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      active.value = (active.value + 1) % results.value.length
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      active.value = active.value <= 0 ? results.value.length - 1 : active.value - 1
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const p = results.value[active.value]
      if (p) goProduct(p)
      else goCatalog()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      close()
    }
  }

  return reactive({
    query,
    results,
    loading,
    open,
    active,
    onInput,
    onKeydown,
    close,
    clear,
    goProduct,
    goCatalog,
    displayPrice,
  })
}
