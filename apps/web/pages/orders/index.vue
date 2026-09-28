<script setup lang="ts">
import type { OrderStatus, OrderSummary } from '~/domain/api/v2/order.schema'
import { AppProblem } from '~/domain/api/v2/problem'
import { ORDER_STATUS_META, ORDER_STATUS_TABS } from '~/utils/order-status'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Мои заявки' })

const route = useRoute()
const router = useRouter()

const { list, repeat } = useOrdersV2()
const PER_PAGE = 10

const STATUS_TABS = ORDER_STATUS_TABS
const STATUS_META = ORDER_STATUS_META

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TOTAL_RE = /^\d{1,12}(\.\d{1,2})?$/

const loading = ref(true)
const error = ref('')
const orders = ref<OrderSummary[]>([])
const statusFilter = ref<'' | OrderStatus>('')
const page = ref(1)
const hasMore = ref(false)
const nextCursor = ref<string | null>(null)
const repeatingId = ref<string | null>(null)
let cursorHistory: Array<string | null> = [null]

// Фильтры живут в URL так же, как в каталоге: читаем query при загрузке
// страницы (восстановление на F5) и заменяем его при каждом запросе списка.
function queryString(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}
function queryDate(key: string): string {
  const value = queryString(key)
  return DATE_RE.test(value) ? value : ''
}
function queryTotal(key: string): string {
  const value = queryString(key)
  return TOTAL_RE.test(value) ? value : ''
}

const q = ref(queryString('q'))
const filters = reactive({
  dateFrom: queryDate('date_from'),
  dateTo: queryDate('date_to'),
  minTotal: queryTotal('min_total'),
  maxTotal: queryTotal('max_total'),
})
// В запрос и URL уходят только полные значения: промежуточный ввод суммы
// («12.») не должен ни ломать контракт API, ни портить ссылку.
const appliedFilters = computed(() => ({
  q: q.value.trim() || undefined,
  dateFrom: filters.dateFrom || undefined,
  dateTo: filters.dateTo || undefined,
  minTotal: TOTAL_RE.test(filters.minTotal) ? filters.minTotal : undefined,
  maxTotal: TOTAL_RE.test(filters.maxTotal) ? filters.maxTotal : undefined,
}))
const activeFilterCount = computed(() => Object.values(appliedFilters.value).filter(Boolean).length)
const hasActiveFilters = computed(() => activeFilterCount.value > 0)

let loadSeq = 0
let isUnmounted = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

function problemMessage(cause: unknown, fallback: string): string {
  return cause instanceof AppProblem ? cause.message : getErrorMessage(cause, fallback)
}

async function load() {
  const seq = ++loadSeq
  const requestedStatus = statusFilter.value
  const requestedCursor = cursorHistory[page.value - 1] ?? undefined
  const applied = appliedFilters.value
  loading.value = true
  error.value = ''
  try {
    const result = await list({
      status: requestedStatus || undefined,
      q: applied.q,
      dateFrom: applied.dateFrom,
      dateTo: applied.dateTo,
      minTotal: applied.minTotal,
      maxTotal: applied.maxTotal,
      limit: PER_PAGE,
      cursor: requestedCursor,
    })
    if (seq !== loadSeq || isUnmounted) return
    orders.value = result.orders
    hasMore.value = result.hasMore
    nextCursor.value = result.nextCursor
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    error.value = problemMessage(cause, 'Не удалось загрузить заявки')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }

  const urlQuery: Record<string, string> = {}
  if (applied.q) urlQuery.q = applied.q
  if (applied.dateFrom) urlQuery.date_from = applied.dateFrom
  if (applied.dateTo) urlQuery.date_to = applied.dateTo
  if (applied.minTotal) urlQuery.min_total = applied.minTotal
  if (applied.maxTotal) urlQuery.max_total = applied.maxTotal
  void router.replace({ query: urlQuery }).catch(() => {})
}

function resetPosition() {
  page.value = 1
  cursorHistory = [null]
}

function applyFilters() {
  resetPosition()
  void load()
}

// Debounce ~300 мс, как поиск в каталоге: печатаем — запрос уходит после паузы.
function queueApply() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(applyFilters, 300)
}
function onSearchInput(value: string) {
  q.value = value
  queueApply()
}
function onFilterInput(key: 'dateFrom' | 'dateTo' | 'minTotal' | 'maxTotal', value: string) {
  filters[key] = value
  queueApply()
}

function resetFilters() {
  q.value = ''
  filters.dateFrom = ''
  filters.dateTo = ''
  filters.minTotal = ''
  filters.maxTotal = ''
  statusFilter.value = ''
  resetPosition()
  void load()
}

function applyStatus(status: '' | OrderStatus) {
  if (statusFilter.value === status) return
  statusFilter.value = status
  resetPosition()
  void load()
}

async function repeatOrder(order: OrderSummary) {
  if (repeatingId.value) return
  repeatingId.value = order.id
  error.value = ''
  try {
    await repeat(order.id, order.version)
    await navigateTo('/cart')
  } catch (cause) {
    error.value = problemMessage(cause, 'Не удалось повторить заявку')
  } finally {
    repeatingId.value = null
  }
}

function goPrevious() {
  if (page.value <= 1) return
  page.value -= 1
  void load()
}

function goNext() {
  const cursor = nextCursor.value
  if (!hasMore.value || !cursor) return
  cursorHistory[page.value] = cursor
  page.value += 1
  void load()
}

const { activeId: pdfActiveId, error: pdfError, exportOrderPdf } = usePdfExport()

onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
  if (searchTimer) clearTimeout(searchTimer)
})

onMounted(load)
</script>

<template>
  <div class="min-w-0" data-testid="orders-page">
    <PageHeading
      eyebrow="История"
      title="Мои заявки"
      :description="loading ? 'Загрузка…' : `На странице: ${orders.length} ${pluralize(orders.length, 'заявка', 'заявки', 'заявок')}`"
      data-testid="orders-heading"
    >
      <template #actions>
        <NuxtLink to="/catalog" class="inline-flex min-h-11 items-center justify-center gap-2 border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">
          <Icon name="heroicons:plus" class="size-4" />Новая заявка
        </NuxtLink>
      </template>
    </PageHeading>

    <div class="mb-5 overflow-x-auto" data-testid="orders-status-filter">
      <div class="flex min-w-max gap-1 border-b border-border" role="tablist" aria-label="Фильтр по статусу">
        <button v-for="tab in STATUS_TABS" :key="tab.value || 'all'" type="button" role="tab" class="min-h-11 border-b-2 px-3 text-sm font-semibold transition-colors" :class="statusFilter === tab.value ? 'border-action text-action' : 'border-transparent text-ink-muted hover:text-ink'" :aria-selected="statusFilter === tab.value" :data-testid="`orders-status-${tab.value || 'all'}`" @click="applyStatus(tab.value)">{{ tab.label }}</button>
      </div>
    </div>

    <section class="mb-5 border border-border bg-surface" data-testid="orders-filter-panel" aria-label="Фильтры заявок">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <h2 class="text-sm font-bold text-ink">Фильтры</h2>
        <span v-if="activeFilterCount" class="numeric border border-action bg-action-soft px-1.5 py-0.5 text-xs font-semibold text-action" data-testid="orders-filter-count">{{ activeFilterCount }}</span>
        <p class="ml-auto hidden text-xs text-ink-muted sm:block">Номер, SKU и комментарий — в поиске</p>
        <button type="button" class="inline-flex min-h-11 items-center gap-2 px-3 text-sm font-semibold text-ink hover:bg-surface-2" data-testid="orders-filter-reset" @click="resetFilters">
          <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />Сбросить
        </button>
      </div>
      <div class="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-6">
        <div class="sm:col-span-2 lg:col-span-2">
          <UiField for="orders-filter-q" label="Поиск">
            <input
              id="orders-filter-q"
              :value="q"
              type="search"
              placeholder="Номер заявки, SKU, комментарий"
              class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
              data-testid="orders-filter-q"
              @input="onSearchInput(($event.target as HTMLInputElement).value)"
            >
          </UiField>
        </div>
        <UiField for="orders-filter-date-from" label="Дата с">
          <input
            id="orders-filter-date-from"
            :value="filters.dateFrom"
            type="date"
            class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
            data-testid="orders-filter-date-from"
            @input="onFilterInput('dateFrom', ($event.target as HTMLInputElement).value)"
          >
        </UiField>
        <UiField for="orders-filter-date-to" label="Дата по">
          <input
            id="orders-filter-date-to"
            :value="filters.dateTo"
            type="date"
            class="block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
            data-testid="orders-filter-date-to"
            @input="onFilterInput('dateTo', ($event.target as HTMLInputElement).value)"
          >
        </UiField>
        <UiField for="orders-filter-min-total" label="Сумма от">
          <input
            id="orders-filter-min-total"
            :value="filters.minTotal"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            placeholder="0.00"
            class="numeric block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
            data-testid="orders-filter-min-total"
            @input="onFilterInput('minTotal', ($event.target as HTMLInputElement).value)"
          >
        </UiField>
        <UiField for="orders-filter-max-total" label="Сумма до">
          <input
            id="orders-filter-max-total"
            :value="filters.maxTotal"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            placeholder="0.00"
            class="numeric block min-h-11 w-full border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-focus focus:outline-none focus:ring-1 focus:ring-focus"
            data-testid="orders-filter-max-total"
            @input="onFilterInput('maxTotal', ($event.target as HTMLInputElement).value)"
          >
        </UiField>
      </div>
    </section>

    <UiErrorState v-if="error && orders.length" class="mb-4" title="Не удалось обновить список" :description="error" data-testid="orders-error" @retry="load" />
    <UiErrorState v-if="pdfError" class="mb-4" title="PDF недоступен" :description="pdfError" data-testid="orders-pdf-error" />

    <div v-if="loading" class="border-y border-border" data-testid="orders-loading" aria-live="polite" aria-busy="true">
      <UiSkeleton v-for="i in 4" :key="i" class="h-16 w-full border-b border-border last:border-b-0" />
      <span class="sr-only">Загрузка заявок</span>
    </div>

    <UiEmptyState v-else-if="!orders.length && !error && hasActiveFilters" title="Ничего не найдено" description="По заданным фильтрам заявок нет. Измените условия поиска или сбросьте фильтры." icon="heroicons:magnifying-glass" data-testid="orders-empty-filtered">
      <template #action><button type="button" class="inline-flex min-h-11 items-center border border-border px-4 text-sm font-semibold" data-testid="orders-empty-reset" @click="resetFilters">Сбросить фильтры</button></template>
    </UiEmptyState>

    <UiEmptyState v-else-if="!orders.length && !error" title="Заявок пока нет" description="Выберите товары в каталоге, чтобы создать первую заявку." icon="heroicons:clipboard-document-list" data-testid="orders-empty">
      <template #action><NuxtLink to="/catalog" class="inline-flex min-h-11 items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover">Перейти в каталог</NuxtLink></template>
    </UiEmptyState>

    <UiErrorState v-else-if="error && !orders.length" class="border-y border-border" title="Заявки недоступны" :description="error" data-testid="orders-error" @retry="load" />

    <template v-else>
      <div class="hidden border border-border bg-surface md:block" data-testid="orders-table">
        <UiTableFrame caption="Заявки клиента" overflow-label="Список заявок с горизонтальной прокруткой">
          <template #header>
            <tr class="border-b border-border bg-surface-2 text-xs font-semibold text-ink-muted">
              <th scope="col" class="px-4 py-3">Заявка</th><th scope="col" class="px-4 py-3">Дата</th><th scope="col" class="px-4 py-3">Статус</th><th scope="col" class="px-4 py-3 text-right">Сумма</th><th scope="col" class="w-px px-4 py-3 text-right"><span class="sr-only">Действия</span></th>
            </tr>
          </template>
          <tr v-for="order in orders" :key="order.id" class="border-b border-border last:border-b-0 hover:bg-surface-2" :data-testid="`orders-row-${order.id}`">
            <td class="px-4 py-3.5"><NuxtLink :to="`/orders/${encodeURIComponent(order.id)}`" class="font-semibold text-ink hover:text-action" :data-testid="`orders-open-${order.id}`">{{ formatOrderNumber(order.sequence, order.id) }}</NuxtLink></td>
            <td class="whitespace-nowrap px-4 py-3.5 text-sm text-ink-muted">{{ formatDate(order.createdAt) }}</td>
            <td class="px-4 py-3.5"><UiStatusBadge :tone="STATUS_META[order.status].tone" :label="STATUS_META[order.status].label" dot /></td>
            <td class="numeric whitespace-nowrap px-4 py-3.5 text-right font-semibold text-ink">{{ formatMoney(order.total.amount, order.total.currency) }}</td>
            <td class="w-px whitespace-nowrap px-4 py-3 text-right">
              <NuxtLink :to="`/orders/${encodeURIComponent(order.id)}`" class="inline-flex min-h-8 items-center justify-center gap-2 px-2.5 py-1 text-xs font-semibold text-ink hover:bg-surface-2"><Icon name="heroicons:eye" class="size-4" />Открыть</NuxtLink>
              <UiButton variant="ghost" size="compact" :loading="repeatingId === order.id" :disabled="repeatingId !== null" :data-testid="`orders-repeat-${order.id}`" @click="repeatOrder(order)"><template #leading><Icon name="heroicons:arrow-path" class="size-4" /></template>Повторить</UiButton>
              <UiButton variant="ghost" size="compact" :loading="pdfActiveId === order.id" :disabled="pdfActiveId !== null" :data-testid="`orders-pdf-${order.id}`" @click="exportOrderPdf(order.id)"><template #leading><Icon name="heroicons:document-arrow-down" class="size-4" /></template>PDF</UiButton>
            </td>
          </tr>
        </UiTableFrame>
      </div>

      <div class="border-y border-border md:hidden" data-testid="orders-cards">
        <article v-for="order in orders" :key="order.id" class="border-b border-border bg-surface px-4 py-4 last:border-b-0" :data-testid="`orders-card-${order.id}`">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0"><NuxtLink :to="`/orders/${encodeURIComponent(order.id)}`" class="font-semibold text-ink hover:text-action" :data-testid="`orders-card-open-${order.id}`">{{ formatOrderNumber(order.sequence, order.id) }}</NuxtLink><p class="mt-1 text-xs text-ink-muted">{{ formatDate(order.createdAt) }}</p></div>
            <p class="numeric shrink-0 font-semibold text-ink">{{ formatMoney(order.total.amount, order.total.currency) }}</p>
          </div>
          <div class="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3">
            <UiStatusBadge :tone="STATUS_META[order.status].tone" :label="STATUS_META[order.status].label" dot />
            <div class="flex items-center gap-1">
              <NuxtLink :to="`/orders/${encodeURIComponent(order.id)}`" class="flex size-11 items-center justify-center text-ink hover:bg-surface-2" :aria-label="`Открыть ${formatOrderNumber(order.sequence, order.id)}`"><Icon name="heroicons:eye" class="size-4" /></NuxtLink>
              <UiButton variant="ghost" size="compact" class="min-h-11" :loading="repeatingId === order.id" :disabled="repeatingId !== null" :aria-label="`Повторить ${formatOrderNumber(order.sequence, order.id)}`" :data-testid="`orders-card-repeat-${order.id}`" @click="repeatOrder(order)"><Icon name="heroicons:arrow-path" class="size-4" /></UiButton>
              <UiButton variant="ghost" size="compact" class="min-h-11" :loading="pdfActiveId === order.id" :disabled="pdfActiveId !== null" :aria-label="`Скачать PDF ${formatOrderNumber(order.sequence, order.id)}`" @click="exportOrderPdf(order.id)"><Icon name="heroicons:document-arrow-down" class="size-4" /></UiButton>
            </div>
          </div>
        </article>
      </div>
    </template>

    <nav v-if="!loading && orders.length && (page > 1 || hasMore)" class="mt-6 flex items-center justify-between gap-3 border-t border-border pt-4" data-testid="orders-pagination" aria-label="Пагинация заявок">
      <UiButton variant="outline" size="touch" :disabled="page <= 1 || loading" aria-label="Предыдущая страница" data-testid="orders-prev" @click="goPrevious"><template #leading><Icon name="heroicons:chevron-left" class="size-4" /></template>Назад</UiButton>
      <span class="text-sm text-ink-muted" data-testid="orders-page-indicator">Страница {{ page }}</span>
      <UiButton variant="outline" size="touch" :disabled="!hasMore || !nextCursor || loading" aria-label="Следующая страница" data-testid="orders-next" @click="goNext">Вперёд<template #trailing><Icon name="heroicons:chevron-right" class="size-4" /></template></UiButton>
    </nav>
  </div>
</template>
