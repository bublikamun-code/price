<script setup lang="ts">
// Список заявок клиента. См. SITEMAP.md §6.
import type { OrderListPage, OrderRead, OrderStatus } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Мои заявки' })

const { request } = useApi()
const PER_PAGE = 10

const STATUS_TABS: { value: '' | OrderStatus; label: string }[] = [
  { value: '', label: 'Все' },
  { value: 'NEW', label: 'Новые' },
  { value: 'IN_PROGRESS', label: 'В работе' },
  { value: 'SHIPPED', label: 'Отгружены' },
  { value: 'COMPLETED', label: 'Завершены' },
  { value: 'CANCELLED', label: 'Отменены' },
]

const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

// Способ получения (приходит опционально — рендерим по наличию).
type DeliveryMethod = 'pickup' | 'delivery'
// types/api.ts пока без поля — расширяем локально.
type OrderRow = OrderRead & { delivery_method?: DeliveryMethod | null }
const DELIVERY_LABEL: Record<DeliveryMethod, string> = {
  pickup: 'Самовывоз',
  delivery: 'Доставка',
}
function deliveryLabel(m?: string | null): string | null {
  if (!m || !(m in DELIVERY_LABEL)) return null
  return DELIVERY_LABEL[m as DeliveryMethod]
}

const loading = ref(true)
const error = ref('')
const orders = ref<OrderRow[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref<'' | OrderStatus>('')
const repeatingId = ref<string | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<OrderListPage>('/api/v1/orders', {
      query: { status: statusFilter.value || undefined, page: page.value, per_page: PER_PAGE },
    })
    orders.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить заявки')
  } finally {
    loading.value = false
  }
}

function applyStatus(s: '' | OrderStatus) {
  statusFilter.value = s
  page.value = 1
  load()
}

async function repeatOrder(o: OrderRead) {
  repeatingId.value = o.id
  error.value = ''
  try {
    await request(`/api/v1/orders/${o.id}/repeat`, { method: 'POST' })
    await navigateTo('/cart')
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось повторить заказ')
  } finally {
    repeatingId.value = null
  }
}

// PDF-экспорт заявки (§16 п.25): job-паттерн, поллинг в composables/usePdfExport.ts.
// Один активный job за раз: activeId — id заявки этой строки во время подготовки.
const { activeId: pdfActiveId, error: pdfError, exportOrderPdf } = usePdfExport()

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// formatMoney/formatDate/pluralize/formatOrderNumber — автоимпорт из utils/format.ts

// --- Поиск (debounce 300ms, клиентская фильтрация) ---
const searchQuery = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null
const debouncedSearch = ref('')

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    debouncedSearch.value = searchQuery.value
  }, 300)
}

// --- Фильтр по дате (клиентский) ---
const dateFrom = ref('')
const dateTo = ref('')

function applyFilters() {
  // Триггер пересчёта filteredOrders (computed уже реактивный,
  // но функция нужна для явного @change на input[type=date]).
}

const filteredOrders = computed(() => {
  let result = orders.value

  // Поиск по номеру
  const q = debouncedSearch.value.trim().toLowerCase()
  if (q) {
    result = result.filter(o => {
      const num = formatOrderNumber(o.seq, o.id).toLowerCase()
      return num.includes(q) || o.id.toLowerCase().includes(q)
    })
  }

  // Фильтр по дате
  if (dateFrom.value) {
    const from = new Date(dateFrom.value).getTime()
    result = result.filter(o => new Date(o.created_at).getTime() >= from)
  }
  if (dateTo.value) {
    const to = new Date(dateTo.value).getTime() + 86400000 // включительно до конца дня
    result = result.filter(o => new Date(o.created_at).getTime() < to)
  }

  return result
})

// --- Windowed pagination (первая, последняя, ±2 соседа, …) ---
function paginationWindow(total: number, current: number, window = 2): (number | '...')[] {
  const pages: (number | '...')[] = []
  const start = Math.max(2, current - window)
  const end = Math.min(total - 1, current + window)
  pages.push(1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  if (total > 1) pages.push(total)
  return pages
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Мои заявки</h1>
      <p class="text-sm text-ink-muted mt-1">
        <template v-if="!loading">{{ total }} {{ pluralize(total, 'заявка', 'заявки', 'заявок') }}</template>
        <template v-else>Загрузка…</template>
      </p>
    </div>

    <!-- Фильтр статусов -->
    <div class="flex flex-wrap gap-2 mb-4">
      <button
        v-for="tab in STATUS_TABS"
        :key="tab.value || 'all'"
        class="px-3.5 py-1.5 rounded-pill text-sm font-medium transition-colors"
        :class="statusFilter === tab.value ? 'bg-primary text-white' : 'bg-surface border border-border text-ink-muted hover:border-primary/60'"
        @click="applyStatus(tab.value)"
      >{{ tab.label }}</button>
    </div>

    <!-- Поиск по номеру + фильтр по дате -->
    <div class="flex flex-wrap items-center gap-3 mb-6">
      <input
        v-model="searchQuery"
        type="text"
        class="input max-w-xs"
        placeholder="Поиск по номеру заявки…"
        @input="onSearchInput"
      >
      <div class="flex items-center gap-2">
        <input v-model="dateFrom" type="date" class="input max-w-[160px]" @change="applyFilters">
        <span class="text-ink-muted text-sm">—</span>
        <input v-model="dateTo" type="date" class="input max-w-[160px]" @change="applyFilters">
      </div>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>
    <div v-if="pdfError" class="mb-4">
      <div class="badge-warning">{{ pdfError }}</div>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 4" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!orders.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:clipboard-document-list" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="mb-4">Заявок пока нет</p>
      <NuxtLink to="/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
    </div>

    <div v-else-if="!filteredOrders.length" class="card p-8 text-center text-ink-muted">
      <Icon name="heroicons:magnifying-glass" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
      <p>Ничего не найдено по заданным фильтрам</p>
    </div>

    <template v-else>
      <!-- Таблица: планшет/десктоп -->
      <div class="card overflow-hidden hidden md:block">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-4 py-3 font-medium">Заявка</th>
                <th class="px-4 py-3 font-medium text-right">Сумма</th>
                <th class="px-4 py-3 font-medium">Статус</th>
                <th class="px-4 py-3 font-medium text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in filteredOrders" :key="o.id" class="border-t border-border hover:bg-canvas/60">
                <td class="px-4 py-3.5 whitespace-nowrap">
                  <div class="font-semibold text-sm" :title="o.id">{{ formatOrderNumber(o.seq, o.id) }} <span class="text-ink-faint">·</span> <span class="text-ink-muted font-normal">{{ formatDate(o.created_at) }}</span></div>
                  <div v-if="deliveryLabel(o.delivery_method)" class="text-xs text-ink-faint mt-0.5">
                    {{ deliveryLabel(o.delivery_method) }}<template v-if="o.delivery_method === 'pickup'"> · склад</template>
                  </div>
                </td>
                <td class="px-4 py-3.5 text-right font-bold">{{ formatMoney(o.total_amount, o.currency_code) }}</td>
                <td class="px-4 py-3.5">
                  <span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span>
                </td>
                <td class="px-4 py-3 text-right whitespace-nowrap">
                  <NuxtLink :to="`/orders/${o.id}`" class="btn-ghost text-sm py-1.5">
                    <Icon name="heroicons:eye" class="w-4 h-4" /> Открыть
                  </NuxtLink>
                  <button
                    class="btn-ghost text-sm py-1.5"
                    :disabled="repeatingId === o.id"
                    @click="repeatOrder(o)"
                  >
                    <span v-if="repeatingId === o.id" class="w-3.5 h-3.5 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                    <Icon v-else name="heroicons:arrow-path" class="w-4 h-4" /> Повторить
                  </button>
                  <button
                    class="btn-ghost text-sm py-1.5"
                    :disabled="pdfActiveId !== null"
                    @click="exportOrderPdf(o.id)"
                  >
                    <span v-if="pdfActiveId === o.id" class="w-3.5 h-3.5 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                    <Icon v-else name="heroicons:document-arrow-down" class="w-4 h-4" /> PDF
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Карточки: мобильные (таблица на 390px не влезает) -->
      <div class="md:hidden flex flex-col gap-3">
        <article v-for="o in filteredOrders" :key="o.id" class="card p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="font-semibold text-sm" :title="o.id">{{ formatOrderNumber(o.seq, o.id) }}</p>
              <p class="text-sm text-ink-muted mt-0.5">
                {{ formatDate(o.created_at) }}<template v-if="deliveryLabel(o.delivery_method)"> · {{ deliveryLabel(o.delivery_method) }}</template>
              </p>
            </div>
            <p class="font-bold whitespace-nowrap shrink-0">{{ formatMoney(o.total_amount, o.currency_code) }}</p>
          </div>
          <div class="flex items-center justify-between gap-2 mt-3 flex-wrap">
            <span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span>
            <div class="flex items-center gap-1 -mr-2">
              <NuxtLink
                :to="`/orders/${o.id}`"
                class="btn-ghost p-2"
                aria-label="Открыть"
                title="Открыть"
              >
                <Icon name="heroicons:eye" class="w-4 h-4" />
              </NuxtLink>
              <button
                class="btn-ghost p-2"
                :disabled="repeatingId === o.id"
                aria-label="Повторить"
                title="Повторить"
                @click="repeatOrder(o)"
              >
                <span v-if="repeatingId === o.id" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                <Icon v-else name="heroicons:arrow-path" class="w-4 h-4" />
              </button>
              <button
                class="btn-ghost p-2"
                :disabled="pdfActiveId !== null"
                aria-label="Скачать PDF"
                title="Скачать PDF"
                @click="exportOrderPdf(o.id)"
              >
                <span v-if="pdfActiveId === o.id" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
                <Icon v-else name="heroicons:document-arrow-down" class="w-4 h-4" />
              </button>
            </div>
          </div>
        </article>
      </div>
    </template>

    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <template v-for="(pgn, idx) in paginationWindow(totalPages, page)" :key="idx">
        <span v-if="pgn === '...'" class="w-10 h-10 flex items-center justify-center text-ink-faint text-sm">…</span>
        <button
          v-else
          class="w-10 h-10 rounded-pill font-medium text-sm"
          :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
          @click="goPage(pgn)"
        >{{ pgn }}</button>
      </template>
      <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>
  </div>
</template>
