<script setup lang="ts">
import type { OrderStatus, OrderSummary } from '~/domain/api/v2/order.schema'
import { ORDER_STATUS_META } from '~/utils/order-status'
import type {
  FileAsset,
  FileAssetPage,
  FileDownloadOut,
} from '~/types/api'

interface ClientDashboardData {
  kpi: {
    orders_total: number
    orders_this_month: number
    total_spent_byn: string
    avg_order_byn: string
  }
  status_counts: Array<{ status: string; count: number }>
  recent_orders: Array<{
    id: string
    created_at: string
    status: string
    total_amount: string
    seq: number | null
  }>
}

const STATUS_META = ORDER_STATUS_META

const auth = useAuth()
const ordersV2 = useOrdersV2()
const cartV2 = useCartV2()
const sessionContext = useSessionContext()
const { request } = useApi()

const loading = ref(true)
const error = ref('')
const dashboard = ref<ClientDashboardData | null>(null)
const recentOrders = ref<OrderSummary[]>([])
const documents = ref<FileAsset[]>([])
const documentsError = ref('')
const downloadingId = ref<string | null>(null)

const firstName = computed(() => auth.user?.name?.trim().split(/\s+/)[0] || 'клиент')
const activeOrganization = computed(() => {
  const context = sessionContext.store.context
  if (!context) return auth.user?.company || null
  if (context.commercialScope === 'USER') return 'Личная заявка'
  return context.memberships.find((item) => item.organizationId === context.organizationId)?.displayName
    || context.memberships.find((item) => item.organizationId === context.organizationId)?.legalName
    || 'Организация'
})
const activeCount = computed(() => {
  const count = dashboard.value?.status_counts
    .filter((item) => item.status === 'NEW' || item.status === 'IN_PROGRESS')
    .reduce((sum, item) => sum + item.count, 0)
  return count ?? 0
})

function statusMeta(status: OrderStatus) {
  return STATUS_META[status]
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

async function downloadDocument(file: FileAsset) {
  if (downloadingId.value) return
  downloadingId.value = file.id
  documentsError.value = ''
  try {
    const result = await request<FileDownloadOut & { data?: FileDownloadOut }>(
      `/api/v1/files/${file.id}/download`,
    )
    window.open((result.data ?? result).url, '_blank', 'noopener')
  } catch (cause) {
    documentsError.value = getErrorMessage(cause, 'Не удалось получить ссылку на документ')
  } finally {
    downloadingId.value = null
  }
}

async function load() {
  loading.value = true
  error.value = ''
  documentsError.value = ''

  const [dashboardOutcome, ordersOutcome, filesOutcome] = await Promise.allSettled([
    request<ClientDashboardData>('/api/v1/dashboard'),
    ordersV2.list({ limit: 5 }),
    request<FileAssetPage>('/api/v1/files', { query: { page: 1, per_page: 3 } }),
  ])

  if (dashboardOutcome.status === 'fulfilled') dashboard.value = dashboardOutcome.value
  if (ordersOutcome.status === 'fulfilled') recentOrders.value = ordersOutcome.value.orders
  if (filesOutcome.status === 'fulfilled') documents.value = filesOutcome.value.data

  const errors = [dashboardOutcome, ordersOutcome]
    .filter((outcome) => outcome.status === 'rejected')
    .map((outcome) => (outcome as PromiseRejectedResult).reason)
  if (errors.length) error.value = getErrorMessage(errors[0], 'Не удалось загрузить кабинет')
  if (filesOutcome.status === 'rejected') {
    documentsError.value = getErrorMessage(filesOutcome.reason, 'Не удалось загрузить документы')
  }

  await Promise.allSettled([
    sessionContext.ensureLoaded(),
    cartV2.ensureLoaded(),
  ])
  loading.value = false
}

let requested = false
watch(
  () => [auth.isAuthenticated, auth.isClient] as const,
  ([authenticated, client]) => {
    if (authenticated && client && !requested) {
      requested = true
      void load()
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="min-w-0">
    <PageHeading
      :eyebrow="activeOrganization || 'Кабинет клиента'"
      :title="`Добрый день, ${firstName}.`"
      description="Заявки, документы и актуальные цены по вашим условиям собраны в одном рабочем разделе."
    >
      <template #actions>
        <NuxtLink
          to="/catalog"
          class="inline-flex min-h-11 items-center justify-center gap-2 border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover"
        >
          Открыть каталог
          <Icon name="heroicons:arrow-right" class="size-4" aria-hidden="true" />
        </NuxtLink>
      </template>
    </PageHeading>

    <UiErrorState
      v-if="error && !dashboard && !recentOrders.length"
      class="mt-6"
      title="Кабинет недоступен"
      :description="error"
      @retry="load"
    />

    <section class="mt-6" aria-labelledby="dashboard-stats-title">
      <div class="mb-3 flex items-center justify-between gap-3">
        <h2 id="dashboard-stats-title" class="text-lg font-bold text-ink">Сводка</h2>
        <span v-if="loading" class="text-xs text-ink-muted">Обновление…</span>
      </div>
      <div v-if="loading && !dashboard" class="grid border border-border bg-surface sm:grid-cols-2 lg:grid-cols-4" aria-busy="true">
        <div v-for="index in 4" :key="index" class="border-b border-border p-4 last:border-b-0 sm:border-r sm:[&:nth-child(2)]:border-r-0 lg:border-b-0 lg:border-r lg:last:border-r-0">
          <UiSkeleton class="h-3 w-1/2" />
          <UiSkeleton class="mt-3 h-7 w-2/3" />
        </div>
      </div>
      <dl v-else-if="dashboard" class="grid border border-border bg-surface sm:grid-cols-2 lg:grid-cols-4">
        <div class="border-b border-border p-4 sm:border-r lg:border-b-0">
          <dt class="text-xs font-semibold text-ink-muted">Всего заявок</dt>
          <dd class="numeric mt-2 text-2xl font-bold text-ink">{{ dashboard.kpi.orders_total }}</dd>
        </div>
        <div class="border-b border-border p-4 lg:border-b-0 lg:border-r">
          <dt class="text-xs font-semibold text-ink-muted">В этом месяце</dt>
          <dd class="numeric mt-2 text-2xl font-bold text-ink">{{ dashboard.kpi.orders_this_month }}</dd>
        </div>
        <div class="border-b border-border p-4 sm:border-b-0 sm:border-r">
          <dt class="text-xs font-semibold text-ink-muted">Сумма заказов</dt>
          <dd class="numeric mt-2 text-lg font-bold text-ink">{{ formatMoney(dashboard.kpi.total_spent_byn, 'BYN') }}</dd>
        </div>
        <div class="p-4">
          <dt class="text-xs font-semibold text-ink-muted">Средний заказ</dt>
          <dd class="numeric mt-2 text-lg font-bold text-ink">{{ formatMoney(dashboard.kpi.avg_order_byn, 'BYN') }}</dd>
        </div>
      </dl>
      <p v-if="dashboard" class="mt-2 text-xs text-ink-muted">
        Активных заявок сейчас: {{ activeCount }}.
      </p>
    </section>

    <div class="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1.6fr)_minmax(20rem,0.8fr)]">
      <section aria-labelledby="dashboard-orders-title">
        <div class="mb-3 flex items-center justify-between gap-4">
          <div>
            <p class="text-xs font-semibold text-ink-muted">Последние заявки</p>
            <h2 id="dashboard-orders-title" class="mt-1 text-lg font-bold text-ink">История поставок</h2>
          </div>
          <NuxtLink to="/orders" class="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-action hover:underline">
            Все заявки
            <Icon name="heroicons:arrow-right" class="size-4" aria-hidden="true" />
          </NuxtLink>
        </div>

        <div v-if="loading && !recentOrders.length" class="border-y border-border" aria-busy="true">
          <UiSkeleton v-for="index in 3" :key="index" class="my-4 h-12 w-full" />
        </div>
        <div v-else-if="!recentOrders.length" class="border-y border-border py-8 text-sm text-ink-muted">
          Заявок пока нет.
        </div>
        <div v-else class="border-t border-border">
          <NuxtLink
            v-for="order in recentOrders"
            :key="order.id"
            :to="`/orders/${encodeURIComponent(order.id)}`"
            class="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border py-3 hover:bg-surface-2 sm:grid-cols-[minmax(0,1fr)_10rem_9rem_auto] sm:px-2"
          >
            <div class="min-w-0">
              <strong class="numeric block truncate text-sm text-ink">{{ formatOrderNumber(order.sequence, order.id) }}</strong>
              <span class="mt-0.5 block text-xs text-ink-muted">{{ formatDate(order.createdAt) }}</span>
            </div>
            <UiStatusBadge class="justify-self-start" :tone="statusMeta(order.status).tone" :label="statusMeta(order.status).label" dot />
            <strong class="numeric col-start-2 row-start-2 text-sm text-ink sm:col-start-auto sm:row-start-auto">
              {{ formatMoney(order.total.amount, order.total.currency) }}
            </strong>
            <Icon name="heroicons:chevron-right" class="hidden size-4 justify-self-end text-ink-muted sm:block" aria-hidden="true" />
          </NuxtLink>
        </div>
      </section>

      <div class="space-y-8">
        <section aria-labelledby="dashboard-navigation-title">
          <p class="text-xs font-semibold text-ink-muted">Навигация</p>
          <h2 id="dashboard-navigation-title" class="mb-3 mt-1 text-lg font-bold text-ink">Рабочие разделы</h2>
          <nav class="border-t border-border">
            <NuxtLink to="/cart" class="flex min-h-11 items-center gap-3 border-b border-border py-2 text-sm font-semibold text-ink hover:text-action">
              <Icon name="heroicons:shopping-cart" class="size-4 text-ink-muted" aria-hidden="true" />
              Текущая заявка
              <span v-if="cartV2.store.cart" class="numeric ml-auto text-ink-muted">{{ cartV2.store.cart.totalItems }}</span>
              <Icon name="heroicons:chevron-right" class="ml-auto size-4 text-ink-muted" aria-hidden="true" />
            </NuxtLink>
            <NuxtLink to="/orders" class="flex min-h-11 items-center gap-3 border-b border-border py-2 text-sm font-semibold text-ink hover:text-action">
              <Icon name="heroicons:arrow-path" class="size-4 text-ink-muted" aria-hidden="true" />
              Повторить заказ
              <Icon name="heroicons:chevron-right" class="ml-auto size-4 text-ink-muted" aria-hidden="true" />
            </NuxtLink>
            <NuxtLink to="/bulk-add" class="flex min-h-11 items-center gap-3 border-b border-border py-2 text-sm font-semibold text-ink hover:text-action">
              <Icon name="heroicons:document-plus" class="size-4 text-ink-muted" aria-hidden="true" />
              Добавить спецификацию
              <Icon name="heroicons:chevron-right" class="ml-auto size-4 text-ink-muted" aria-hidden="true" />
            </NuxtLink>
            <NuxtLink to="/profile" class="flex min-h-11 items-center gap-3 border-b border-border py-2 text-sm font-semibold text-ink hover:text-action">
              <Icon name="heroicons:user-circle" class="size-4 text-ink-muted" aria-hidden="true" />
              Профиль и настройки
              <Icon name="heroicons:chevron-right" class="ml-auto size-4 text-ink-muted" aria-hidden="true" />
            </NuxtLink>
          </nav>
        </section>

        <section aria-labelledby="dashboard-documents-title">
          <div class="mb-3 flex items-center justify-between gap-3">
            <div>
              <p class="text-xs font-semibold text-ink-muted">Документы</p>
              <h2 id="dashboard-documents-title" class="mt-1 text-lg font-bold text-ink">Доступные файлы</h2>
            </div>
            <NuxtLink to="/files" class="inline-flex min-h-11 items-center text-sm font-semibold text-action hover:underline">Все</NuxtLink>
          </div>
          <p v-if="documentsError" class="mb-2 text-xs text-danger-text" role="alert">{{ documentsError }}</p>
          <div v-if="loading && !documents.length" class="border-y border-border py-3 text-sm text-ink-muted" aria-busy="true">Загрузка…</div>
          <div v-else-if="!documents.length" class="border-y border-border py-6 text-sm text-ink-muted">Документов пока нет.</div>
          <div v-else class="border-t border-border">
            <button
              v-for="file in documents"
              :key="file.id"
              type="button"
              class="flex min-h-11 w-full items-center gap-3 border-b border-border py-2 text-left text-sm hover:bg-surface-2 disabled:opacity-50"
              :disabled="downloadingId !== null"
              @click="downloadDocument(file)"
            >
              <Icon name="heroicons:document-text" class="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate">{{ file.filename }}</span>
              <span class="numeric shrink-0 text-xs text-ink-muted">{{ fileSize(file.size_bytes) }}</span>
              <UiSpinner v-if="downloadingId === file.id" :size="14" />
              <Icon v-else name="heroicons:arrow-down-tray" class="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            </button>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
