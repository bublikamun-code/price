<script setup lang="ts">
// Лента заявок менеджера. См. SITEMAP.md §7, §9 (FSM), §11 (RBAC).
import type { OrderListPage, OrderRead, OrderStatus } from '~/types/api'
import { ORDER_STATUS_META, ORDER_STATUS_TABS } from '~/utils/order-status'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Заявки — Менеджер' })

const { request } = useApi()
const PER_PAGE = 15

const STATUS_TABS = ORDER_STATUS_TABS
const STATUS_META = ORDER_STATUS_META

// Быстрые кнопки переходов статусов прямо из списка (§9 FSM)
const QUICK_ACTIONS: Partial<Record<OrderStatus, { label: string; next: OrderStatus; cls: string }>> = {
  NEW: { label: 'В сборку', next: 'IN_PROGRESS', cls: 'btn-primary' },
  IN_PROGRESS: { label: 'Отгрузить', next: 'SHIPPED', cls: 'btn-primary' },
  SHIPPED: { label: 'Завершить', next: 'COMPLETED', cls: 'btn-primary' },
}

const loading = ref(true)
const error = ref('')
const orders = ref<OrderRead[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref<'' | OrderStatus>('')
const changingId = ref<string | null>(null)

// Поиск (клиентская фильтрация по текущей странице с 300ms debounce)
const searchQuery = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null
const debouncedSearch = ref('')

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    debouncedSearch.value = searchQuery.value.trim()
  }, 300)
}

// Сортировка (клиентская)
const sortField = ref<'created_at' | 'client_name' | 'total_amount'>('created_at')
const sortDir = ref<'asc' | 'desc'>('desc')

function toggleSort(field: typeof sortField.value) {
  if (sortField.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortDir.value = 'desc'
  }
}

function sortIcon(field: string): string {
  if (sortField.value !== field) return 'heroicons:chevron-up-down'
  return sortDir.value === 'asc' ? 'heroicons:chevron-up' : 'heroicons:chevron-down'
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

// client_name / client_company / seq приходят из API (см. types/api.ts OrderRead)
const orderRows = computed<OrderRead[]>(() => orders.value)

// Клиентский поиск + сортировка
const displayedRows = computed(() => {
  let result = orderRows.value
  if (debouncedSearch.value) {
    const q = debouncedSearch.value.toLowerCase()
    result = result.filter(o => {
      const num = formatOrderNumber(o.seq, o.id).toLowerCase()
      const name = (o.client_name ?? '').toLowerCase()
      const company = (o.client_company ?? '').toLowerCase()
      return num.includes(q) || name.includes(q) || company.includes(q)
    })
  }
  return [...result].sort((a, b) => {
    const dir = sortDir.value === 'asc' ? 1 : -1
    if (sortField.value === 'created_at') {
      return dir * (new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    }
    if (sortField.value === 'client_name') {
      return dir * (a.client_name ?? '').localeCompare(b.client_name ?? '', 'ru')
    }
    // total_amount
    return dir * (Number(a.total_amount) - Number(b.total_amount))
  })
})

// Подсчёт статусов из текущей страницы
const statusCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const o of orders.value) {
    counts[o.status] = (counts[o.status] || 0) + 1
  }
  return counts
})

// Окно пагинации (1 ... 4 5 6 ... 20)
function paginationWindow(totalPg: number, current: number, window = 2): (number | '...')[] {
  const pages: (number | '...')[] = []
  const start = Math.max(2, current - window)
  const end = Math.min(totalPg - 1, current + window)
  pages.push(1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < totalPg - 1) pages.push('...')
  if (totalPg > 1) pages.push(totalPg)
  return pages
}

const paginationPages = computed(() => paginationWindow(totalPages.value, page.value))

let loadSeq = 0
let isUnmounted = false

async function load() {
  const seq = ++loadSeq
  // Параметры фиксируются на старте, чтобы быстрые клики не смешивали ответы.
  const requestedStatus = statusFilter.value
  const requestedPage = page.value
  loading.value = true
  error.value = ''
  try {
    const res = await request<OrderListPage>('/api/v1/manager/orders', {
      query: { status: requestedStatus || undefined, page: requestedPage, per_page: PER_PAGE },
    })
    if (seq !== loadSeq || isUnmounted) return
    orders.value = res.data
    total.value = res.meta.total
  } catch (e) {
    if (seq !== loadSeq || isUnmounted) return
    error.value = getErrorMessage(e, 'Не удалось загрузить заявки')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }
}

async function quickChangeStatus(order: OrderRead, next: OrderStatus) {
  if (changingId.value) return
  changingId.value = order.id
  error.value = ''
  try {
    const updated = await request<OrderRead>(`/api/v1/manager/orders/${order.id}`, {
      method: 'PATCH',
      body: { status: next },
    })
    // Обновляем карточку в списке без перезагрузки всей страницы
    const idx = orders.value.findIndex(o => o.id === order.id)
    if (idx !== -1) orders.value[idx] = updated
    // Если активен фильтр по статусу — убираем карточку из текущей колонки
    if (statusFilter.value && statusFilter.value !== updated.status) {
      orders.value.splice(idx, 1)
      total.value = Math.max(0, total.value - 1)
    }
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось изменить статус')
  } finally {
    changingId.value = null
  }
}

function applyStatus(s: '' | OrderStatus) {
  statusFilter.value = s
  page.value = 1
  load()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU')
}

onUnmounted(() => {
  isUnmounted = true
  loadSeq++
  if (searchTimer) clearTimeout(searchTimer)
})

onMounted(load)
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Заявки"
      :description="loading ? 'Загрузка…' : `${total} заявок`"
    />

    <!-- Поиск -->
    <div class="mb-4 max-w-sm">
      <div class="relative">
        <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
        <input
          v-model="searchQuery"
          type="search"
          class="input pl-10"
          placeholder="Поиск по номеру или клиенту…"
          @input="onSearchInput"
        >
      </div>
    </div>

    <!-- Фильтр статусов -->
    <div class="flex flex-wrap gap-2 mb-6">
      <button
        v-for="tab in STATUS_TABS"
        :key="tab.value || 'all'"
        class="btn-outline min-h-11 px-3 text-sm"
        :class="statusFilter === tab.value ? 'border-action bg-action text-white' : 'bg-surface text-ink-muted hover:border-action'"
        @click="applyStatus(tab.value)"
      >
        {{ tab.label }}
        <span v-if="!tab.value ? orders.length : statusCounts[tab.value]" class="text-xs opacity-70">
          {{ !tab.value ? orders.length : (statusCounts[tab.value] || 0) }}
        </span>
      </button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="border border-border bg-surface p-4">
      <div v-for="i in 5" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!displayedRows.length" class="border border-border bg-surface p-6 text-ink-muted">
      <Icon name="heroicons:clipboard-document-list" class="size-8 mb-3 text-ink-faint" />
      <p>{{ debouncedSearch ? 'По этому запросу ничего не найдено' : 'Заявок по этому фильтру нет' }}</p>
    </div>

    <div v-else class="border border-border bg-surface">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">№</th>
              <th class="px-4 py-3 font-medium cursor-pointer select-none hover:text-ink" @click="toggleSort('created_at')">
                <span class="inline-flex items-center gap-1">Дата <Icon :name="sortIcon('created_at')" class="w-3.5 h-3.5" /></span>
              </th>
              <th class="px-4 py-3 font-medium cursor-pointer select-none hover:text-ink" @click="toggleSort('client_name')">
                <span class="inline-flex items-center gap-1">Клиент <Icon :name="sortIcon('client_name')" class="w-3.5 h-3.5" /></span>
              </th>
              <th class="px-4 py-3 font-medium text-right cursor-pointer select-none hover:text-ink" @click="toggleSort('total_amount')">
                <span class="inline-flex items-center justify-end gap-1">Сумма <Icon :name="sortIcon('total_amount')" class="w-3.5 h-3.5" /></span>
              </th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium text-right">Действие</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in displayedRows" :key="o.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 font-mono text-xs whitespace-nowrap" :title="o.id">{{ formatOrderNumber(o.seq, o.id) }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(o.created_at) }}</td>
              <td class="px-4 py-3">
                <div :title="o.client_id">{{ o.client_name ?? '№' + o.client_id.slice(0, 8) }}</div>
                <div v-if="o.client_company" class="text-xs text-ink-muted mt-0.5">{{ o.client_company }}</div>
              </td>
              <td class="px-4 py-3 text-right font-semibold whitespace-nowrap">{{ formatMoney(o.total_amount, o.currency_code) }}</td>
              <td class="px-4 py-3">
                <UiStatusBadge :tone="STATUS_META[o.status].tone" :label="STATUS_META[o.status].label" dot />
              </td>
              <td class="px-4 py-3 text-right">
                <div class="flex items-center justify-end gap-2">
                  <!-- Быстрая кнопка перехода статуса (В сборку / Отгрузить / Завершить) -->
                  <button
                    v-if="QUICK_ACTIONS[o.status]"
                    class="btn-primary min-h-11 px-3 text-xs"
                    :disabled="changingId === o.id"
                    @click.prevent="quickChangeStatus(o, QUICK_ACTIONS[o.status]!.next)"
                  >
                    <span v-if="changingId === o.id" class="w-3 h-3 border-2 border-white/40 border-t-white rounded-sm animate-spin"/>
                    <template v-else>{{ QUICK_ACTIONS[o.status]!.label }}</template>
                  </button>
                  <NuxtLink :to="`/manager/orders/${o.id}`" class="btn-ghost min-h-11 text-sm">
                    <Icon name="heroicons:eye" class="w-4 h-4" /> Открыть
                  </NuxtLink>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button class="btn-ghost size-11" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <template v-for="(pgn, idx) in paginationPages" :key="idx">
        <span v-if="pgn === '...'" class="w-10 h-10 flex items-center justify-center text-ink-faint text-sm">…</span>
        <button
          v-else
          class="btn-outline size-11 font-medium text-sm"
          :class="pgn === page ? 'border-action bg-action text-white' : 'text-ink-muted hover:bg-surface-2'"
          @click="goPage(pgn as number)"
        >{{ pgn }}</button>
      </template>
      <button class="btn-ghost size-11" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>
  </div>
</template>
