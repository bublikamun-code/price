<script setup lang="ts">
// Мобильный список заявок (Mini App): карточки с раскрытием позиций.
import type { OrderItemRead, OrderListPage, OrderRead, OrderStatus } from '~/types/api'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
useHead({ title: 'Мои заявки' })

const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

const { request } = useApi()
const loading = ref(true)
const error = ref('')
const orders = ref<OrderRead[]>([])
const expandedId = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<OrderListPage>('/api/v1/orders', { query: { page: 1, per_page: 50 } })
    orders.value = res.data
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить заявки')
  } finally {
    loading.value = false
  }
}

/** Раскрыть/свернуть позиции заявки. */
function toggle(o: OrderRead) {
  if (!o.items?.length) return
  expandedId.value = expandedId.value === o.id ? null : o.id
}

function snapName(item: OrderItemRead): string {
  const name = (item.product_snapshot as { name?: unknown }).name
  const sku = (item.product_snapshot as { sku?: unknown }).sku
  return (typeof name === 'string' && name) || (typeof sku === 'string' && sku) || '—'
}
function shortId(id: string) {
  return id.slice(0, 8)
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-lg font-bold mb-3">Мои заявки</h1>

    <div v-if="error" class="flex items-center gap-3 mb-3">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <!-- Skeleton -->
    <div v-if="loading" class="card p-4">
      <div v-for="i in 4" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0" />
    </div>

    <!-- Пусто -->
    <div v-else-if="!orders.length" class="card p-8 text-center">
      <Icon name="heroicons:clipboard-document-list" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
      <p class="text-sm text-ink-muted mb-4">Заявок пока нет</p>
      <NuxtLink to="/m/catalog" class="btn-primary">Перейти в каталог</NuxtLink>
    </div>

    <!-- Список -->
    <div v-else class="flex flex-col gap-3">
      <article
        v-for="o in orders"
        :key="o.id"
        class="card p-4"
        :class="o.items?.length ? 'cursor-pointer active:bg-canvas/60' : ''"
        @click="toggle(o)"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="font-semibold text-sm"> №{{ shortId(o.id) }} <span class="font-normal text-ink-muted">· {{ formatDate(o.created_at) }}</span></p>
            <div class="mt-1.5">
              <span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span>
            </div>
          </div>
          <div class="text-right shrink-0">
            <p class="font-bold">{{ formatMoney(o.total_amount, o.currency_code) }}</p>
            <Icon v-if="o.items?.length" name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint mx-auto mt-1 transition-transform" :class="expandedId === o.id ? 'rotate-180' : ''" />
          </div>
        </div>

        <div v-if="expandedId === o.id && o.items?.length" class="border-t border-border mt-3 pt-3 flex flex-col gap-2">
          <div v-for="item in o.items" :key="item.id" class="flex items-center justify-between gap-3 text-sm">
            <div class="min-w-0">
              <p class="line-clamp-1">{{ snapName(item) }}</p>
              <p class="text-xs text-ink-faint">{{ item.quantity }} шт × {{ formatMoney(item.unit_price, item.currency_code) }}</p>
            </div>
            <span class="font-medium shrink-0">{{ formatMoney(item.quantity * item.unit_price, item.currency_code) }}</span>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
