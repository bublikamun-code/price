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

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<NotificationsPage>('/api/v1/notifications', {
      query: { page: page.value, per_page: PER_PAGE, type: typeFilter.value || undefined },
    })
    items.value = res.data
    total.value = res.meta.total
    unreadTotal.value = res.meta.unread_count ?? 0
    // Бейдж шапки обновляем только из загрузки без фильтра
    // (unread_count — свои непрочитанные; при фильтре семантика не гарантирована).
    if (!typeFilter.value) unreadCount.value = unreadTotal.value
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить уведомления')
  } finally {
    loading.value = false
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

onMounted(load)
</script>

<template>
  <div>
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <h1 class="text-2xl font-bold">Уведомления</h1>
      <button class="btn-outline" :disabled="markingAll || !unreadTotal" @click="markAll">
        <span v-if="markingAll" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
        <Icon v-else name="heroicons:check" class="w-4 h-4" />
        Отметить все прочитанными
      </button>
    </div>

    <!-- Фильтр по типу -->
    <div class="flex flex-wrap gap-2 mb-6">
      <button
        v-for="f in TYPE_FILTERS"
        :key="f.value || 'all'"
        class="px-3.5 py-1.5 rounded-pill text-sm font-medium transition-colors"
        :class="typeFilter === f.value ? 'bg-primary text-white' : 'bg-surface border border-border text-ink-muted hover:border-primary/60'"
        @click="applyType(f.value)"
      >{{ f.label }}</button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 4" :key="i" class="skeleton h-16 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!items.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:bell-slash" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>Нет уведомлений</p>
    </div>

    <!-- Timeline-список -->
    <div v-else class="flex flex-col gap-3">
      <div
        v-for="n in items"
        :key="n.id"
        class="card p-4 flex items-start gap-3 transition-colors"
        :class="n.is_read ? '' : 'border-primary/30 bg-primary/5 cursor-pointer hover:border-primary/50'"
        :title="n.is_read ? '' : 'Отметить прочитанным'"
        @click="markRead(n)"
      >
        <span class="w-9 h-9 shrink-0 rounded-pill flex items-center justify-center" :class="typeMeta(n.type).cls">
          <Icon :name="typeMeta(n.type).icon" class="w-5 h-5" />
        </span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-medium text-sm">{{ n.title }}</span>
            <span class="chip bg-canvas text-ink-muted">{{ typeMeta(n.type).label }}</span>
            <span v-if="n.is_broadcast" class="chip bg-canvas text-ink-muted" title="Массовая рассылка">Всем</span>
          </div>
          <p v-if="n.body" class="text-sm text-ink-muted mt-1">{{ n.body }}</p>
          <p class="text-xs text-ink-faint mt-1.5">{{ formatDateTime(n.created_at) }}</p>
        </div>
        <span v-if="!n.is_read" class="w-2.5 h-2.5 shrink-0 mt-2 rounded-pill bg-primary" :class="markingId === n.id ? 'animate-pulse' : ''"/>
      </div>
    </div>

    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <button
        v-for="pgn in totalPages"
        :key="pgn"
        class="w-10 h-10 rounded-pill font-medium text-sm"
        :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
        @click="goPage(pgn)"
      >{{ pgn }}</button>
      <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>
  </div>
</template>
