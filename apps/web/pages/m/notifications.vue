<script setup lang="ts">
// Мобильные уведомления (Mini App): список, клик по непрочитанному — отметить прочитанным.
import type { NotificationItem, NotificationsPage } from '~/types/api'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
useHead({ title: 'Уведомления' })
const { request } = useApi()
const { unreadCount } = useNotifications()

const TYPE_META: Record<string, { label: string; icon: string; cls: string }> = {
  NEW_ORDER: { label: 'Новая заявка', icon: 'heroicons:document-plus', cls: 'bg-surface-2 text-primary' },
  ORDER_STATUS_CHANGED: { label: 'Статус заявки', icon: 'heroicons:arrow-path', cls: 'bg-surface-2 text-primary' },
  PRICE_CHANGED: { label: 'Изменение цен', icon: 'heroicons:banknotes', cls: 'bg-surface-2 text-primary' },
  PRICE_CHANGED_DIGEST: { label: 'Дайджест цен', icon: 'heroicons:chart-bar', cls: 'bg-surface-2 text-primary' },
  STOCK_CHANGED: { label: 'Наличие', icon: 'heroicons:cube', cls: 'bg-warning-soft text-warning' },
  IMPORT_FAILED: { label: 'Ошибка импорта', icon: 'heroicons:exclamation-triangle', cls: 'bg-danger-soft text-danger' },
  RATE_FETCH_FAILED: { label: 'Курс НБ РБ', icon: 'heroicons:currency-dollar', cls: 'bg-danger-soft text-danger' },
  ACCOUNT_CREATED: { label: 'Доступ создан', icon: 'heroicons:user-plus', cls: 'bg-surface-2 text-primary' },
}
function typeMeta(t: string) {
  return TYPE_META[t] ?? { label: t, icon: 'heroicons:bell', cls: 'bg-surface-2 text-primary' }
}

const items = ref<NotificationItem[]>([])
const loading = ref(true)
const error = ref('')
const markingId = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<NotificationsPage>('/api/v1/notifications', { query: { page: 1, per_page: 50 } })
    items.value = res.data
    unreadCount.value = res.meta?.unread_count ?? 0
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить уведомления')
  } finally {
    loading.value = false
  }
}

/** Клик по непрочитанному → отметить прочитанным (локально + бейдж). */
async function markRead(n: NotificationItem) {
  if (n.is_read || markingId.value) return
  markingId.value = n.id
  try {
    await request(`/api/v1/notifications/${n.id}/read`, { method: 'PATCH' })
    n.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось отметить уведомление')
  } finally {
    markingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-lg font-bold mb-3">Уведомления</h1>

    <div v-if="error" class="flex items-center gap-3 mb-3">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <!-- Skeleton -->
    <div v-if="loading" class="card p-4">
      <div v-for="i in 4" :key="i" class="skeleton h-16 w-full mb-3 last:mb-0" />
    </div>

    <!-- Пусто -->
    <div v-else-if="!items.length" class="card p-8 text-center">
      <Icon name="heroicons:bell-slash" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
      <p class="text-sm text-ink-muted">Нет уведомлений</p>
    </div>

    <!-- Список -->
    <div v-else class="flex flex-col gap-2.5">
      <div
        v-for="n in items"
        :key="n.id"
        class="card p-3.5 flex items-start gap-3 transition-colors"
        :class="n.is_read ? '' : 'border-primary/30 bg-primary/5 cursor-pointer active:border-primary/50'"
        :title="n.is_read ? '' : 'Отметить прочитанным'"
        @click="markRead(n)"
      >
        <span class="w-8 h-8 shrink-0 rounded-pill flex items-center justify-center" :class="typeMeta(n.type).cls">
          <Icon :name="typeMeta(n.type).icon" class="w-4 h-4" />
        </span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-medium text-sm leading-snug">{{ n.title }}</span>
            <span class="chip bg-canvas text-ink-muted !px-2 !py-0.5">{{ typeMeta(n.type).label }}</span>
          </div>
          <p v-if="n.body" class="text-xs text-ink-muted mt-1">{{ n.body }}</p>
          <p class="text-[11px] text-ink-faint mt-1">{{ formatDateTime(n.created_at) }}</p>
        </div>
        <span v-if="!n.is_read" class="w-2.5 h-2.5 shrink-0 mt-1.5 rounded-pill bg-primary" :class="markingId === n.id ? 'animate-pulse' : ''" />
      </div>
    </div>
  </div>
</template>
