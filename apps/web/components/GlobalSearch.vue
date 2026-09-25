<script setup lang="ts">
const auth = useAuth()
const router = useRouter()
const route = useRoute()
const open = ref(false)
const cursor = ref(0)
const searchInput = shallowRef<HTMLInputElement | null>(null)
const dialogPanel = shallowRef<HTMLElement | null>(null)
const uid = useId()
const typeahead = useSearchTypeahead({ debounceMs: 250, perPage: 6 })

useFocusTrap(dialogPanel, () => open.value, {
  initialFocus: () => searchInput.value,
})

interface SearchResult {
  title: string
  subtitle?: string
  icon: string
  to: string
  group: string
}

const navItems = computed<SearchResult[]>(() => {
  if (auth.isManager || auth.isAdmin) {
    return [
      { title: 'Дашборд менеджера', icon: 'heroicons:presentation-chart-bar', to: '/manager', group: 'Управление' },
      { title: 'Управление каталогом', icon: 'heroicons:cog-6-tooth', to: '/manager/catalog', group: 'Управление' },
      { title: 'Импорт прайсов', icon: 'heroicons:arrow-up-tray', to: '/manager/import', group: 'Управление' },
      { title: 'Клиенты', icon: 'heroicons:users', to: '/manager/users', group: 'Управление' },
      { title: 'Заявки', icon: 'heroicons:inbox-stack', to: '/manager/orders', group: 'Управление' },
      { title: 'Аудит', icon: 'heroicons:shield-check', to: '/manager/audit', group: 'Управление' },
    ]
  }
  if (auth.isClient) {
    return [
      { title: 'Главная', icon: 'heroicons:home', to: '/dashboard', group: 'Навигация' },
      { title: 'Каталог', icon: 'heroicons:squares-2x2', to: '/catalog', group: 'Навигация' },
      { title: 'Избранное', icon: 'heroicons:heart', to: '/favorites', group: 'Навигация' },
      { title: 'Мои заявки', icon: 'heroicons:clipboard-document-list', to: '/orders', group: 'Навигация' },
      { title: 'Корзина', icon: 'heroicons:shopping-cart', to: '/cart', group: 'Навигация' },
      { title: 'Массовое добавление', icon: 'heroicons:plus-circle', to: '/bulk-add', group: 'Навигация' },
      { title: 'Аналитика', icon: 'heroicons:chart-bar', to: '/analytics', group: 'Навигация' },
      { title: 'Файлы', icon: 'heroicons:document-text', to: '/files', group: 'Навигация' },
      { title: 'Профиль', icon: 'heroicons:user-circle', to: '/profile', group: 'Навигация' },
      { title: 'Уведомления', icon: 'heroicons:bell', to: '/notifications', group: 'Навигация' },
    ]
  }
  return [
    { title: 'Бренды', icon: 'heroicons:tag', to: '/brands', group: 'Каталог' },
    { title: 'Новости', icon: 'heroicons:newspaper', to: '/news', group: 'Разделы' },
  ]
})

const query = computed({
  get: () => typeahead.query,
  set: (value: string) => { typeahead.query = value },
})
const productResults = computed<SearchResult[]>(() => typeahead.results.map((product) => ({
  title: product.name,
  subtitle: `Арт. ${product.sku}${product.brand ? ` · ${product.brand.name}` : ''}`,
  icon: 'heroicons:cube',
  to: `/catalog/${encodeURIComponent(product.sku)}`,
  group: 'Товары',
})))

const results = computed(() => {
  const normalized = query.value.toLowerCase().trim()
  const navigation = normalized.length >= 1
    ? navItems.value.filter((item) => item.title.toLowerCase().includes(normalized) || item.to.toLowerCase().includes(normalized))
    : navItems.value.slice(0, 8)
  return [...navigation, ...productResults.value]
})

const groupedResults = computed(() => {
  const groups: Record<string, { label: string; items: SearchResult[] }> = {}
  for (const result of results.value) {
    groups[result.group] ??= { label: result.group, items: [] }
    groups[result.group]!.items.push(result)
  }
  return groups
})

const emptyMessage = computed(() => {
  if (typeahead.loading) return 'Загрузка результатов…'
  if (!query.value.trim()) return 'Начните вводить название или артикул'
  if (query.value.trim().length < 2) return 'Введите ещё один символ'
  if (!auth.isAuthenticated && !results.value.length) return 'Войдите, чтобы искать товары в каталоге'
  return 'Ничего не найдено'
})

function flatIndex(groupKey: string, index: number): number {
  let offset = 0
  for (const [key, group] of Object.entries(groupedResults.value)) {
    if (key === groupKey) return offset + index
    offset += group.items.length
  }
  return 0
}

function moveCursor(direction: number) {
  const total = results.value.length
  if (total) cursor.value = (cursor.value + direction + total) % total
}

function navigate(item: SearchResult) {
  close()
  void router.push(item.to)
}

function submitSearch() {
  const selected = results.value[cursor.value]
  if (selected) {
    navigate(selected)
    return
  }
  const normalized = query.value.trim()
  if (normalized.length < 2) return
  close()
  void router.push({ path: '/catalog', query: { q: normalized } })
}

function close() {
  open.value = false
  typeahead.clear()
  cursor.value = 0
}

function openSearch() {
  open.value = true
  nextTick(() => searchInput.value?.focus())
}

function onGlobalKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    if (open.value) close()
    else openSearch()
    return
  }
  if (open.value && event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

function onOpenRequest() {
  openSearch()
}

watch(query, () => {
  cursor.value = 0
  if (!auth.isAuthenticated) {
    typeahead.clear()
    return
  }
  typeahead.onInput()
})

watch(() => auth.isAuthenticated, () => {
  if (open.value && query.value.trim().length >= 2) typeahead.onInput()
})

watch(() => route.fullPath, () => {
  if (open.value) close()
})

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('price:open-search', onOpenRequest)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('price:open-search', onOpenRequest)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" @click.self="close">
      <button type="button" class="absolute inset-0 bg-ink/60" aria-label="Закрыть поиск" @click="close" />
      <section
        id="global-search-dialog"
        ref="dialogPanel"
        class="relative flex max-h-[calc(100dvh-2rem)] w-full max-w-2xl flex-col border border-border-strong bg-surface shadow-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="global-search-title"
      >
        <h2 id="global-search-title" class="sr-only">Глобальный поиск</h2>
        <div class="flex min-h-14 items-center gap-3 border-b border-border px-4">
          <Icon name="heroicons:magnifying-glass" class="size-5 shrink-0 text-ink-muted" aria-hidden="true" />
          <input
            id="global-search-input"
            ref="searchInput"
            v-model="query"
            type="search"
            role="combobox"
            aria-label="Поиск по порталу"
            :aria-expanded="open"
            aria-haspopup="listbox"
            aria-controls="global-search-results"
            :aria-activedescendant="results[cursor] ? `${uid}-result-${cursor}` : undefined"
            class="min-h-11 min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-muted"
            placeholder="Поиск по порталу…"
            @keydown.escape.prevent="close"
            @keydown.enter.prevent="submitSearch"
            @keydown.arrow-down.prevent="moveCursor(1)"
            @keydown.arrow-up.prevent="moveCursor(-1)"
          >
          <kbd class="hidden border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink-muted sm:inline">ESC</kbd>
        </div>

        <div id="global-search-results" class="min-h-0 overflow-y-auto p-2" role="listbox" aria-label="Результаты поиска">
          <div v-for="(group, groupKey) in groupedResults" :key="groupKey" class="mb-2 last:mb-0">
            <p class="px-3 py-2 text-xs font-bold uppercase text-ink-muted">{{ group.label }}</p>
            <button
              v-for="(item, index) in group.items"
              :id="`${uid}-result-${flatIndex(groupKey, index)}`"
              :key="`${groupKey}-${index}-${item.to}`"
              type="button"
              class="flex min-h-12 w-full items-center gap-3 border-l-2 px-3 py-2 text-left transition-colors"
              :class="flatIndex(groupKey, index) === cursor ? 'border-action bg-surface-2' : 'border-transparent hover:bg-surface-2'"
              role="option"
              :aria-selected="flatIndex(groupKey, index) === cursor"
              @click="navigate(item)"
              @mouseenter="cursor = flatIndex(groupKey, index)"
            >
              <Icon :name="item.icon" class="size-5 shrink-0 text-ink-muted" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-ink">{{ item.title }}</span>
                <span v-if="item.subtitle" class="block truncate font-mono text-xs text-ink-muted">{{ item.subtitle }}</span>
              </span>
              <Icon name="heroicons:arrow-right" class="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            </button>
          </div>
          <p v-if="!results.length || (typeahead.loading && query.trim().length >= 2)" class="px-4 py-8 text-center text-sm text-ink-muted" :aria-busy="typeahead.loading">
            {{ emptyMessage }}
          </p>
        </div>
        <div class="flex items-center justify-between border-t border-border px-4 py-2 font-mono text-xs text-ink-muted">
          <span>↑↓ выбор · ↵ открыть</span><span>CTRL K</span>
        </div>
      </section>
    </div>
  </Teleport>
</template>
