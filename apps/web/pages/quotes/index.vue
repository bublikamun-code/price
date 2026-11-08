<script setup lang="ts">
// Лента КП клиента (Э8): КП активной организации, DRAFT скрыты на бэенде.
// Курсорная пагинация и табы статусов — тот же паттерн, что в /orders.
import type { QuoteStatus, QuoteSummary } from '~/domain/api/v2/quote.schema'
import { problemMessage } from '~/domain/api/v2/problem'
import { QUOTE_CLIENT_STATUS_TABS, QUOTE_STATUS_META } from '~/utils/quote'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Коммерческие предложения' })

const route = useRoute()
const router = useRouter()
const { repository } = useQuotes()

const STATUS_TABS = QUOTE_CLIENT_STATUS_TABS
const PER_PAGE = 10

const loading = ref(true)
const error = ref('')
const quotes = ref<QuoteSummary[]>([])
const statusFilter = ref<'' | QuoteStatus>(typeof route.query.status === 'string' && QUOTE_CLIENT_STATUS_TABS.some((tab) => tab.value === route.query.status) ? (route.query.status as QuoteStatus) : '')
const page = ref(1)
const hasMore = ref(false)
const nextCursor = ref<string | null>(null)
let cursorHistory: Array<string | null> = [null]

let loadSeq = 0
let isUnmounted = false

async function load() {
  const seq = ++loadSeq
  const requestedStatus = statusFilter.value
  const requestedCursor = cursorHistory[page.value - 1] ?? undefined
  loading.value = true
  error.value = ''
  try {
    const result = await repository.listClient({
      status: requestedStatus || undefined,
      limit: PER_PAGE,
      cursor: requestedCursor,
    })
    if (seq !== loadSeq || isUnmounted) return
    quotes.value = result.quotes
    hasMore.value = result.hasMore
    nextCursor.value = result.nextCursor
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    error.value = problemMessage(cause, 'Не удалось загрузить КП')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }

  const urlQuery: Record<string, string> = {}
  if (requestedStatus) urlQuery.status = requestedStatus
  void router.replace({ query: urlQuery }).catch(() => {})
}

function resetPosition() {
  page.value = 1
  cursorHistory = [null]
}

function applyStatus(status: '' | QuoteStatus) {
  if (statusFilter.value === status) return
  statusFilter.value = status
  resetPosition()
  void load()
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

onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
})

onMounted(load)
</script>

<template>
  <div class="min-w-0" data-testid="quotes-page">
    <PageHeading
      eyebrow="История"
      title="Коммерческие предложения"
      :description="loading ? 'Загрузка…' : `На странице: ${quotes.length} ${pluralize(quotes.length, 'предложение', 'предложения', 'предложений')}`"
      data-testid="quotes-heading"
    />

    <div class="mb-5 overflow-x-auto" data-testid="quotes-status-filter">
      <div class="flex min-w-max gap-1 border-b border-border" role="tablist" aria-label="Фильтр по статусу">
        <button
          v-for="tab in STATUS_TABS"
          :key="tab.value || 'all'"
          type="button"
          role="tab"
          class="min-h-11 border-b-2 px-3 text-sm font-semibold transition-colors"
          :class="statusFilter === tab.value ? 'border-action text-action' : 'border-transparent text-ink-muted hover:text-ink'"
          :aria-selected="statusFilter === tab.value"
          :data-testid="`quotes-status-${tab.value || 'all'}`"
          @click="applyStatus(tab.value)"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <UiErrorState
      v-if="error && !quotes.length"
      title="КП недоступны"
      :description="error"
      data-testid="quotes-error"
      @retry="load"
    />
    <UiErrorState
      v-if="error && quotes.length"
      class="mb-4"
      title="Не удалось обновить список"
      :description="error"
      @retry="load"
    />

    <div v-if="loading" class="border-y border-border" data-testid="quotes-loading" aria-live="polite" aria-busy="true">
      <UiSkeleton v-for="i in 4" :key="i" class="h-16 w-full border-b border-border last:border-b-0" />
      <span class="sr-only">Загрузка КП</span>
    </div>

    <UiEmptyState
      v-else-if="!quotes.length && !error"
      title="КП пока нет"
      description="Когда менеджер подготовит для вас коммерческое предложение, оно появится здесь."
      icon="heroicons:document-text"
      data-testid="quotes-empty"
    />

    <template v-else-if="!error">
      <div class="hidden border border-border bg-surface md:block" data-testid="quotes-table">
        <UiTableFrame caption="Коммерческие предложения" overflow-label="Список КП с горизонтальной прокруткой">
          <template #header>
            <tr class="border-b border-border bg-surface-2 text-xs font-semibold text-ink-muted">
              <th scope="col" class="px-4 py-3">Номер</th>
              <th scope="col" class="px-4 py-3">Создано</th>
              <th scope="col" class="px-4 py-3">Действ. до</th>
              <th scope="col" class="px-4 py-3">Статус</th>
              <th scope="col" class="px-4 py-3 text-right">Сумма</th>
              <th scope="col" class="w-px px-4 py-3 text-right"><span class="sr-only">Действия</span></th>
            </tr>
          </template>
          <tr
            v-for="row in quotes"
            :key="row.id"
            class="border-b border-border last:border-b-0 hover:bg-surface-2"
            :data-testid="`quotes-row-${row.id}`"
          >
            <td class="px-4 py-3.5">
              <NuxtLink
                :to="`/quotes/${encodeURIComponent(row.id)}`"
                class="font-semibold text-ink hover:text-action"
                :data-testid="`quotes-open-${row.id}`"
              >
                {{ row.number ?? 'Без номера' }}
              </NuxtLink>
            </td>
            <td class="whitespace-nowrap px-4 py-3.5 text-sm text-ink-muted">{{ formatDate(row.createdAt) }}</td>
            <td class="whitespace-nowrap px-4 py-3.5 text-sm text-ink-muted">
              {{ row.validUntil ? formatDate(row.validUntil) : '—' }}
            </td>
            <td class="px-4 py-3.5">
              <UiStatusBadge
                :tone="QUOTE_STATUS_META[row.status].tone"
                :label="QUOTE_STATUS_META[row.status].label"
                dot
                :data-testid="`quotes-status-${row.id}`"
              />
            </td>
            <td class="numeric whitespace-nowrap px-4 py-3.5 text-right font-semibold text-ink">
              {{ formatMoney(row.total.amount, row.total.currency) }}
            </td>
            <td class="w-px whitespace-nowrap px-4 py-3 text-right">
              <NuxtLink
                :to="`/quotes/${encodeURIComponent(row.id)}`"
                class="inline-flex min-h-8 items-center justify-center gap-2 px-2.5 py-1 text-xs font-semibold text-ink hover:bg-surface-2"
              >
                <Icon name="heroicons:eye" class="size-4" />Открыть
              </NuxtLink>
            </td>
          </tr>
        </UiTableFrame>
      </div>

      <div class="border-y border-border md:hidden" data-testid="quotes-cards">
        <article
          v-for="row in quotes"
          :key="row.id"
          class="border-b border-border bg-surface px-4 py-4 last:border-b-0"
          :data-testid="`quotes-card-${row.id}`"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0">
              <NuxtLink :to="`/quotes/${encodeURIComponent(row.id)}`" class="font-semibold text-ink hover:text-action">
                {{ row.number ?? 'Без номера' }}
              </NuxtLink>
              <p class="mt-1 text-xs text-ink-muted">Создано {{ formatDate(row.createdAt) }}</p>
              <p class="text-xs text-ink-muted">
                {{ row.validUntil ? `Действует до ${formatDate(row.validUntil)}` : 'Срок не указан' }}
              </p>
            </div>
            <p class="numeric shrink-0 font-semibold text-ink">{{ formatMoney(row.total.amount, row.total.currency) }}</p>
          </div>
          <div class="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3">
            <UiStatusBadge
              :tone="QUOTE_STATUS_META[row.status].tone"
              :label="QUOTE_STATUS_META[row.status].label"
              dot
            />
            <NuxtLink
              :to="`/quotes/${encodeURIComponent(row.id)}`"
              class="inline-flex min-h-11 items-center gap-2 px-3 text-sm font-semibold text-ink hover:bg-surface-2"
            >
              <Icon name="heroicons:eye" class="size-4" />Открыть
            </NuxtLink>
          </div>
        </article>
      </div>
    </template>

    <nav
      v-if="!loading && quotes.length && (page > 1 || hasMore)"
      class="mt-6 flex items-center justify-between gap-3 border-t border-border pt-4"
      data-testid="quotes-pagination"
      aria-label="Пагинация КП"
    >
      <UiButton variant="outline" size="touch" :disabled="page <= 1 || loading" aria-label="Предыдущая страница" data-testid="quotes-prev" @click="goPrevious">
        <template #leading><Icon name="heroicons:chevron-left" class="size-4" /></template>Назад
      </UiButton>
      <span class="text-sm text-ink-muted" data-testid="quotes-page-indicator">Страница {{ page }}</span>
      <UiButton variant="outline" size="touch" :disabled="!hasMore || !nextCursor || loading" aria-label="Следующая страница" data-testid="quotes-next" @click="goNext">
        Вперёд<template #trailing><Icon name="heroicons:chevron-right" class="size-4" /></template>
      </UiButton>
    </nav>
  </div>
</template>
