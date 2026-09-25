<script setup lang="ts">
// Мобильный список заявок (Mini App): карточки с раскрытием позиций.
import type { OrderItemRead, OrderListPage, OrderRead } from '~/types/api'
import { ORDER_STATUS_META } from '~/utils/order-status'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
useHead({ title: 'Мои заявки' })

const STATUS_META = ORDER_STATUS_META

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
    <PageHeading
      eyebrow="История"
      title="Мои заявки"
      :description="`Заявок: ${orders.length}`"
    />

    <div v-if="error" class="mb-4 flex items-center gap-3 border border-danger/50 bg-danger-soft p-3" role="alert">
      <p class="min-w-0 flex-1 text-sm text-ink">{{ error }}</p>
      <button type="button" class="btn-outline min-h-11 shrink-0" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="border border-border bg-surface" aria-label="Загрузка заявок" aria-busy="true">
      <div v-for="i in 4" :key="i" class="h-20 border-b border-border p-3 last:border-b-0"><div class="skeleton h-full w-full" /></div>
    </div>

    <div v-else-if="!orders.length" class="border border-border bg-surface p-5">
      <p class="text-sm font-semibold text-ink">Заявок пока нет</p>
      <p class="mt-1 text-sm text-ink-muted">Сформированные заявки появятся здесь.</p>
      <NuxtLink to="/m/catalog" class="btn-primary mt-4 inline-flex min-h-11 items-center">Перейти в каталог</NuxtLink>
    </div>

    <section v-else class="border border-border bg-surface" aria-label="Список заявок">
      <article v-for="o in orders" :key="o.id" class="border-b border-border last:border-b-0">
        <button
          type="button"
          class="flex min-h-20 w-full items-center gap-3 p-3 text-left hover:bg-surface-2 disabled:cursor-default"
          :disabled="!o.items?.length"
          :aria-expanded="o.items?.length ? expandedId === o.id : undefined"
          @click="toggle(o)"
        >
          <span class="min-w-0 flex-1">
            <span class="numeric block text-sm font-bold text-ink">№{{ shortId(o.id) }}</span>
            <span class="mt-1 block text-xs text-ink-muted">{{ formatDate(o.created_at) }}</span>
            <UiStatusBadge :tone="STATUS_META[o.status].tone" :label="STATUS_META[o.status].label" dot class="mt-2" />
          </span>
          <span class="numeric shrink-0 text-right text-sm font-bold text-ink">{{ formatMoney(o.total_amount, o.currency_code) }}</span>
          <Icon v-if="o.items?.length" name="heroicons:chevron-down" class="size-5 shrink-0 text-ink-muted transition-transform" :class="expandedId === o.id ? 'rotate-180' : ''" aria-hidden="true" />
        </button>
        <div v-if="expandedId === o.id && o.items?.length" class="border-t border-border bg-background px-3">
          <div v-for="item in o.items" :key="item.id" class="flex min-h-14 items-center justify-between gap-3 border-b border-border py-2 last:border-b-0">
            <div class="min-w-0"><p class="truncate text-sm font-medium text-ink">{{ snapName(item) }}</p><p class="numeric mt-0.5 text-xs text-ink-muted">{{ item.quantity }} шт × {{ formatMoney(item.unit_price, item.currency_code) }}</p></div>
            <span class="numeric shrink-0 text-sm font-semibold">{{ formatMoney(item.quantity * item.unit_price, item.currency_code) }}</span>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
