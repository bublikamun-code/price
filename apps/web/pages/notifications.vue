<script setup lang="ts">
// Центр уведомлений (клиент/менеджер). См. SITEMAP.md §6 `/notifications`.
// GET /notifications + PATCH /notifications/{id}/read + PATCH /notifications/read-all.
import type { NotificationItem, NotificationsPage } from '~/types/api'

definePageMeta({
  middleware: [
    'auth',
    // Layout зависит от роли: менеджеру — manager, клиенту — client.
    (to) => {
      const auth = useAuth()
      to.meta.layout = auth.isManager ? 'manager' : 'client'
    },
  ],
})
useHead({ title: 'Уведомления' })

const { request } = useApi()
const auth = useAuth()
const { unreadCount, refresh: refreshBadge } = useNotifications()
const PER_PAGE = 20

// Реестр типов: RU-заголовок + иконка. Неизвестные коды → raw-строка.
const TYPE_META: Record<string, { label: string; icon: string; cls: string }> = {
  NEW_ORDER: { label: 'Новая заявка', icon: 'heroicons:document-plus', cls: 'bg-primary-soft text-primary' },
  ORDER_STATUS_CHANGED: { label: 'Статус заявки', icon: 'heroicons:arrow-path', cls: 'bg-primary-soft text-primary' },
  PRICE_CHANGED: { label: 'Изменение цен', icon: 'heroicons:banknotes', cls: 'bg-primary-soft text-primary' },
  PRICE_CHANGED_DIGEST: { label: 'Дайджест цен', icon: 'heroicons:chart-bar', cls: 'bg-primary-soft text-primary' },
  STOCK_CHANGED: { label: 'Наличие', icon: 'heroicons:cube', cls: 'bg-warning-soft text-warning' },
  IMPORT_FAILED: { label: 'Ошибка импорта', icon: 'heroicons:exclamation-triangle', cls: 'bg-danger-soft text-danger' },
  RATE_FETCH_FAILED: { label: 'Курс НБ РБ', icon: 'heroicons:currency-dollar', cls: 'bg-danger-soft text-danger' },
  ACCOUNT_CREATED: { label: 'Доступ создан', icon: 'heroicons:user-plus', cls: 'bg-primary-soft text-primary' },
  LEAD_CREATED: { label: 'Заявка с сайта', icon: 'heroicons:inbox-arrow-down', cls: 'bg-success-soft text-success' },
}

function typeMeta(t: string) {
  return TYPE_META[t] ?? { label: t, icon: 'heroicons:bell', cls: 'bg-primary-soft text-primary' }
}

/** Маппинг типа уведомления → ссылка на связанный объект. */
function getNotificationLink(n: NotificationItem): string | null {
  const prefix = auth.isManager ? '/manager' : ''
  switch (n.type) {
    case 'NEW_ORDER':
    case 'ORDER_STATUS_CHANGED':
      return n.payload?.order_id ? `${prefix}/orders/${n.payload.order_id}` : `${prefix}/orders`
    case 'PRICE_CHANGED':
      // payload приходит из данных без типизации, поэтому sku приводим к строке
      // явно: иначе значение с `/` или `?` разломало бы путь каталога.
      return n.payload?.sku
        ? `/catalog/${encodeURIComponent(String(n.payload.sku))}`
        : '/catalog'
    case 'PRICE_CHANGED_DIGEST':
    case 'STOCK_CHANGED':
      return '/catalog'
    case 'IMPORT_FAILED':
      return `${prefix}/files`
    case 'LEAD_CREATED':
      return `${prefix}/orders`
    default:
      return null
  }
}

const TYPE_FILTERS: { value: string; label: string }[] = [
  { value: '', label: 'Все' },
  ...Object.entries(TYPE_META).map(([value, m]) => ({ value, label: m.label })),
]

// --- Состояние списка ---
const items = ref<NotificationItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')
const typeFilter = ref('')
const markingAll = ref(false)
const markingId = ref<string | null>(null)
// Локальный счётчик непрочитанных (управляет кнопкой «Отметить все»).
const unreadTotal = ref(0)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

let loadSeq = 0
let isUnmounted = false

async function load() {
  const seq = ++loadSeq
  // Фиксируем страницу и фильтр, чтобы устаревший ответ не переписал новый.
  const requestedPage = page.value
  const requestedType = typeFilter.value
  loading.value = true
  error.value = ''
  try {
    const res = await request<NotificationsPage>('/api/v1/notifications', {
      query: { page: requestedPage, per_page: PER_PAGE, type: requestedType || undefined },
    })
    if (seq !== loadSeq || isUnmounted) return
    items.value = res.data
    total.value = res.meta.total
    unreadTotal.value = res.meta.unread_count ?? 0
    // Бейдж шапки обновляем только из загрузки без фильтра
    // (unread_count — свои непрочитанные; при фильтре семантика не гарантирована).
    if (!requestedType) unreadCount.value = unreadTotal.value
  } catch (e) {
    if (seq !== loadSeq || isUnmounted) return
    error.value = getErrorMessage(e, 'Не удалось загрузить уведомления')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }
}

function applyType(v: string) {
  typeFilter.value = v
  page.value = 1
  load()
}

/** Клик по непрочитанному → отметить прочитанным (локально + бейдж). */
async function markRead(n: NotificationItem) {
  if (n.is_read || markingId.value) return
  markingId.value = n.id
  try {
    await request(`/api/v1/notifications/${n.id}/read`, { method: 'PATCH' })
    n.is_read = true
    unreadTotal.value = Math.max(0, unreadTotal.value - 1)
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось отметить уведомление')
  } finally {
    markingId.value = null
  }
}

async function markAll() {
  if (markingAll.value || !unreadTotal.value) return
  markingAll.value = true
  error.value = ''
  try {
    await request('/api/v1/notifications/read-all', { method: 'PATCH' })
    await load()
    await refreshBadge()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось отметить все уведомления')
  } finally {
    markingAll.value = false
  }
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

function formatDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}

onUnmounted(() => {
  isUnmounted = true
  loadSeq++
})

onMounted(load)
</script>

<template>
  <div>
    <PageHeading eyebrow="Рабочий кабинет" title="Уведомления">
      <template #actions>
        <UiButton variant="outline" size="touch" :loading="markingAll" :disabled="markingAll || !unreadTotal" @click="markAll">
          <template #leading><Icon name="heroicons:check" class="size-4" aria-hidden="true" /></template>
          Отметить все прочитанными
        </UiButton>
      </template>
    </PageHeading>

    <nav class="mt-5 flex flex-wrap gap-2" aria-label="Фильтр уведомлений">
      <button
        v-for="f in TYPE_FILTERS"
        :key="f.value || 'all'"
        class="min-h-11 border px-3.5 text-sm font-medium transition-colors"
        :class="typeFilter === f.value
          ? 'border-action bg-action text-action-on'
          : 'border-border bg-surface text-ink-muted hover:border-ink-muted hover:text-ink'"
        :aria-pressed="typeFilter === f.value"
        @click="applyType(f.value)"
      >{{ f.label }}</button>
    </nav>

    <div v-if="error" class="mt-5 flex flex-col items-start justify-between gap-3 border-y border-danger/30 bg-danger-soft px-4 py-3 sm:flex-row sm:items-center">
      <p class="text-sm text-danger-text" role="alert">{{ error }}</p>
      <button class="btn-ghost min-h-11" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="record-list mt-6" aria-busy="true">
      <div v-for="i in 4" :key="i" class="record">
        <UiSkeleton class="h-12 w-full" />
      </div>
    </div>

    <div v-else-if="!items.length" class="mt-6 border-y border-border py-14 text-center text-ink-muted">
      <Icon name="heroicons:bell-slash" class="mx-auto size-10 text-ink-faint" aria-hidden="true" />
      <p class="mt-3">Нет уведомлений</p>
    </div>

    <section v-else class="record-list mt-6" aria-label="Список уведомлений">
      <article
        v-for="n in items"
        :key="n.id"
        class="record flex items-start gap-3"
        :class="n.is_read ? '' : 'bg-surface-2/60'"
      >
        <span class="flex size-11 shrink-0 items-center justify-center border border-border" :class="typeMeta(n.type).cls">
          <Icon :name="typeMeta(n.type).icon" class="size-5" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold text-ink">{{ n.title }}</span>
            <span class="border border-border bg-surface px-2 py-0.5 text-xs text-ink-muted">{{ typeMeta(n.type).label }}</span>
            <span v-if="n.is_broadcast" class="border border-border bg-surface px-2 py-0.5 text-xs text-ink-muted" title="Массовая рассылка">Всем</span>
            <span v-if="!n.is_read" class="size-2 bg-action" aria-label="Новое уведомление" />
          </div>
          <p v-if="n.body" class="mt-1 text-sm leading-5 text-ink-muted">{{ n.body }}</p>
          <p class="mt-1.5 text-xs text-ink-faint">{{ formatDateTime(n.created_at) }}</p>
          <NuxtLink
            v-if="getNotificationLink(n)"
            :to="getNotificationLink(n) ?? undefined"
            class="mt-2 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-action hover:underline"
          >
            Открыть
            <Icon name="heroicons:arrow-right" class="size-4" aria-hidden="true" />
          </NuxtLink>
        </div>
        <button
          v-if="!n.is_read"
          type="button"
          class="btn-ghost size-11 shrink-0"
          :disabled="markingId === n.id"
          :aria-label="`Отметить уведомление «${n.title}» прочитанным`"
          @click="markRead(n)"
        >
          <UiSpinner v-if="markingId === n.id" :size="14" />
          <Icon v-else name="heroicons:check" class="size-5" aria-hidden="true" />
        </button>
      </article>
    </section>

    <nav v-if="!loading && totalPages > 1" class="mt-6 flex items-center justify-center gap-1" aria-label="Страницы уведомлений">
      <button class="btn-ghost size-11 shrink-0" :disabled="page <= 1" aria-label="Предыдущая страница" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="size-5" />
      </button>
      <button
        v-for="pgn in totalPages"
        :key="pgn"
        class="size-11 border border-border bg-surface font-medium text-sm text-ink transition-colors hover:bg-surface-2"
        :class="pgn === page ? 'bg-action text-action-on' : ''"
        :aria-current="pgn === page ? 'page' : undefined"
        @click="goPage(pgn)"
      >{{ pgn }}</button>
      <button class="btn-ghost size-11 shrink-0" :disabled="page >= totalPages" aria-label="Следующая страница" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="size-5" />
      </button>
    </nav>
  </div>
</template>
