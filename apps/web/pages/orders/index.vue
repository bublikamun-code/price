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

const loading = ref(true)
const error = ref('')
const orders = ref<OrderRead[]>([])
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

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

function shortId(id: string): string {
  return id.slice(0, 8)
}
function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU')
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Мои заявки</h1>
      <p class="text-sm text-ink-muted mt-1">
        <template v-if="!loading">{{ total }} заявок</template>
        <template v-else>Загрузка…</template>
      </p>
    </div>

    <!-- Фильтр статусов -->
    <div class="flex flex-wrap gap-2 mb-6">
      <button
        v-for="tab in STATUS_TABS"
        :key="tab.value || 'all'"
        class="px-3.5 py-1.5 rounded-pill text-sm font-medium transition-colors"
        :class="statusFilter === tab.value ? 'bg-primary text-white' : 'bg-surface border border-border text-ink-muted hover:border-primary/60'"
        @click="applyStatus(tab.value)"
      >{{ tab.label }}</button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 4" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!orders.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:clipboard-document-list" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="mb-4">Заявок пока нет</p>
      <NuxtLink to="/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
    </div>

    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-canvas">
              <th class="px-4 py-3 font-medium">№</th>
              <th class="px-4 py-3 font-medium">Дата</th>
              <th class="px-4 py-3 font-medium text-right">Сумма</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in orders" :key="o.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 font-mono text-xs" :title="o.id">№{{ shortId(o.id) }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(o.created_at) }}</td>
              <td class="px-4 py-3 text-right font-semibold">{{ o.total_amount }} {{ o.currency_code }}</td>
              <td class="px-4 py-3">
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
              </td>
            </tr>
          </tbody>
        </table>
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
