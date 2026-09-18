<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]"
      @click.self="close"
    >
      <div class="absolute inset-0 bg-black/50" />
      <div
        class="relative w-full max-w-xl glass rounded-card shadow-card-hover overflow-hidden"
        role="dialog"
        aria-label="Глобальный поиск"
      >
        <div class="flex items-center gap-3 px-5 py-4 border-b border-border">
          <Icon name="heroicons:magnifying-glass" class="w-5 h-5 text-ink-faint shrink-0" />
          <input
            ref="searchInput"
            v-model="query"
            type="text"
            class="flex-1 bg-transparent text-ink text-base outline-none placeholder:text-ink-faint"
            placeholder="Поиск по порталу…"
            @keydown.escape="close"
            @keydown.enter="selectCurrent"
            @keydown.arrow-down.prevent="moveCursor(1)"
            @keydown.arrow-up.prevent="moveCursor(-1)"
          >
          <kbd class="hidden sm:inline-flex items-center gap-0.5 text-xs text-ink-faint bg-canvas rounded px-1.5 py-0.5 border border-border">
            Esc
          </kbd>
        </div>

        <div v-if="results.length" class="max-h-80 overflow-y-auto p-2">
          <div v-for="(group, gKey) in groupedResults" :key="gKey" class="mb-2 last:mb-0">
            <p class="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              {{ group.label }}
            </p>
            <button
              v-for="(item, i) in group.items"
              :key="`${gKey}-${i}`"
              class="w-full flex items-center gap-3 px-3 py-2.5 rounded-[14px] text-left transition-colors"
              :class="flatIndex(gKey, i) === cursor ? 'bg-accent-soft' : 'hover:bg-canvas'"
              @click="navigate(item)"
              @mouseenter="cursor = flatIndex(gKey, i)"
            >
              <Icon :name="item.icon" class="w-5 h-5 text-ink-faint shrink-0" />
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium truncate">{{ item.title }}</p>
                <p v-if="item.subtitle" class="text-xs text-ink-muted truncate">{{ item.subtitle }}</p>
              </div>
              <Icon name="heroicons:arrow-right" class="w-4 h-4 text-ink-faint shrink-0" />
            </button>
          </div>
        </div>

        <div v-else-if="query.length >= 2" class="p-6 text-center text-sm text-ink-muted">
          <Icon name="heroicons:magnifying-glass" class="w-8 h-8 mx-auto mb-2 text-ink-faint" />
          Ничего не найдено
        </div>

        <div v-else class="p-4 text-center text-xs text-ink-faint">
          Начните вводить для поиска по навигации, товарам и заказам
        </div>

        <div class="flex items-center justify-between px-5 py-2.5 border-t border-border text-xs text-ink-faint">
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1"><kbd class="bg-canvas rounded px-1 py-0.5 border border-border">↑↓</kbd> навигация</span>
            <span class="flex items-center gap-1"><kbd class="bg-canvas rounded px-1 py-0.5 border border-border">↵</kbd> выбрать</span>
          </div>
          <span>Ctrl+K</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
const auth = useAuth()
const router = useRouter()

const open = ref(false)
const query = ref('')
const cursor = ref(0)
const searchInput = ref<HTMLInputElement | null>(null)

interface SearchResult {
  title: string
  subtitle?: string
  icon: string
  to: string
  group: string
}

const navItems = computed<SearchResult[]>(() => {
  const base: SearchResult[] = [
    { title: 'Каталог', icon: 'heroicons:squares-2x2', to: '/catalog', group: 'Навигация' },
    { title: 'Избранное', icon: 'heroicons:heart', to: '/favorites', group: 'Навигация' },
    { title: 'Мои заявки', icon: 'heroicons:clipboard-document-list', to: '/orders', group: 'Навигация' },
    { title: 'Корзина', icon: 'heroicons:shopping-cart', to: '/cart', group: 'Навигация' },
    { title: 'Массовое добавление', icon: 'heroicons:plus-circle', to: '/bulk-add', group: 'Навигация' },
    { title: 'Аналитика', icon: 'heroicons:chart-bar', to: '/dashboard', group: 'Навигация' },
    { title: 'Файлы', icon: 'heroicons:document-text', to: '/files', group: 'Навигация' },
    { title: 'Профиль', icon: 'heroicons:user-circle', to: '/profile', group: 'Навигация' },
    { title: 'Уведомления', icon: 'heroicons:bell', to: '/notifications', group: 'Навигация' },
  ]
  if (auth.isManager || auth.isAdmin) {
    base.push(
      { title: 'Дашборд менеджера', icon: 'heroicons:presentation-chart-bar', to: '/manager', group: 'Управление' },
      { title: 'Управление каталогом', icon: 'heroicons:cog-6-tooth', to: '/manager/catalog', group: 'Управление' },
      { title: 'Импорт прайсов', icon: 'heroicons:arrow-up-tray', to: '/manager/import', group: 'Управление' },
      { title: 'Клиенты', icon: 'heroicons:users', to: '/manager/users', group: 'Управление' },
      { title: 'Заявки (менеджер)', icon: 'heroicons:inbox-stack', to: '/manager/orders', group: 'Управление' },
      { title: 'Бренды и серии', icon: 'heroicons:tag', to: '/manager/brands', group: 'Управление' },
      { title: 'Баннеры', icon: 'heroicons:photo', to: '/manager/banners', group: 'Управление' },
      { title: 'Новости', icon: 'heroicons:newspaper', to: '/manager/news', group: 'Управление' },
      { title: 'Курсы валют', icon: 'heroicons:currency-dollar', to: '/manager/currency', group: 'Управление' },
      { title: 'Аудит', icon: 'heroicons:shield-check', to: '/manager/audit', group: 'Управление' },
    )
  }
  return base
})

const productResults = ref<SearchResult[]>([])

let searchTimer: ReturnType<typeof setTimeout>
watch(query, (val) => {
  clearTimeout(searchTimer)
  cursor.value = 0
  if (val.length < 2) {
    productResults.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    try {
      if (!auth.isAuthenticated) {
        productResults.value = []
        return
      }
      const { request } = useApi()
      const res = await request<{ data: { sku: string; name: string; brand?: { name: string } }[] }>(
        '/api/v1/catalog/products',
        { query: { q: val, page: 1, per_page: 5 } },
      ).catch(() => null)
      productResults.value = (res?.data ?? []).map(p => ({
        title: p.name,
        subtitle: `Арт. ${p.sku}${p.brand?.name ? ` · ${p.brand.name}` : ''}`,
        icon: 'heroicons:cube',
        to: `/catalog/${p.sku}`,
        group: 'Товары',
      }))
    } catch {
      productResults.value = []
    }
  }, 250)
})

const results = computed(() => {
  const q = query.value.toLowerCase().trim()
  const nav = q.length >= 1
    ? navItems.value.filter((n) =>
        n.title.toLowerCase().includes(q) || n.to.toLowerCase().includes(q),
      )
    : navItems.value.slice(0, 8)
  return [...nav, ...productResults.value]
})

const groupedResults = computed(() => {
  const groups: Record<string, { label: string; items: SearchResult[] }> = {}
  for (const r of results.value) {
    if (!groups[r.group]) {
      groups[r.group] = { label: r.group, items: [] }
    }
    groups[r.group].items.push(r)
  }
  return groups
})

function flatIndex(gKey: string, i: number): number {
  let idx = 0
  for (const [key, group] of Object.entries(groupedResults.value)) {
    if (key === gKey) return idx + i
    idx += group.items.length
  }
  return 0
}

function moveCursor(dir: number) {
  const total = results.value.length
  if (!total) return
  cursor.value = (cursor.value + dir + total) % total
}

function selectCurrent() {
  const item = results.value[cursor.value]
  if (item) navigate(item)
}

function navigate(item: SearchResult) {
  close()
  router.push(item.to)
}

function close() {
  open.value = false
  query.value = ''
  cursor.value = 0
  productResults.value = []
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    nextTick(() => searchInput.value?.focus())
  }
}

onMounted(() => {
  const handler = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      toggle()
    }
  }
  window.addEventListener('keydown', handler)
  onBeforeUnmount(() => window.removeEventListener('keydown', handler))
})
</script>
