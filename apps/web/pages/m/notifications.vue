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
    <PageHeading
      eyebrow="События"
      title="Уведомления"
      :description="`Непрочитанных: ${unreadCount}`"
    />

    <div v-if="error" class="mb-4 flex items-center gap-3 border border-danger/50 bg-danger-soft p-3" role="alert">
      <p class="min-w-0 flex-1 text-sm text-ink">{{ error }}</p>
      <button type="button" class="btn-outline min-h-11 shrink-0" @click="load">Повторить</button>
    </div>
    <div v-if="loading" class="border border-border bg-surface" aria-label="Загрузка уведомлений" aria-busy="true">
      <div v-for="i in 4" :key="i" class="h-20 border-b border-border p-3 last:border-b-0"><div class="skeleton h-full w-full" /></div>
    </div>
    <div v-else-if="!items.length" class="border border-border bg-surface p-5"><p class="text-sm font-semibold text-ink">Уведомлений нет</p><p class="mt-1 text-sm text-ink-muted">Новые события появятся в этой ленте.</p></div>
    <section v-else class="border border-border bg-surface" aria-label="Лента уведомлений">
      <button
        v-for="n in items"
        :key="n.id"
        type="button"
        class="flex min-h-20 w-full items-start gap-3 border-b border-border p-3 text-left last:border-b-0 hover:bg-surface-2 disabled:cursor-default"
        :class="n.is_read ? '' : 'bg-info-soft'"
        :disabled="n.is_read || !!markingId"
        :aria-label="n.is_read ? n.title : `${n.title}. Отметить прочитанным`"
        @click="markRead(n)"
      >
        <span class="flex size-9 shrink-0 items-center justify-center border border-border" :class="typeMeta(n.type).cls"><Icon :name="typeMeta(n.type).icon" class="size-4" /></span>
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-semibold uppercase tracking-wide text-ink-muted">{{ typeMeta(n.type).label }}</span>
          <span class="mt-1 block text-sm font-semibold leading-5 text-ink">{{ n.title }}</span>
          <span v-if="n.body" class="mt-1 block text-xs leading-5 text-ink-muted">{{ n.body }}</span>
          <span class="mt-1 block text-xs text-ink-faint">{{ formatDateTime(n.created_at) }}</span>
        </span>
        <UiStatusBadge v-if="!n.is_read" class="mt-1" tone="action" label="Новое" />
      </button>
    </section>
  </div>
</template>
