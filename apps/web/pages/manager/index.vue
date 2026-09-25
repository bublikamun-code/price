<script setup lang="ts">
// Дашборд менеджера (фича G, Этап 8). GET /api/v1/manager/dashboard —
// KPI, заявки по дням (30), топы, последние заявки. Кэш на сервере 60 с,
// поэтому кнопка «Обновить» (данные могут отставать ≤60 с).
import type { DashboardData } from '~/types/api'
import { ORDER_STATUS_META } from '~/utils/order-status'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Дашборд' })

const { request } = useApi()

const STATUS_META = ORDER_STATUS_META

const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const data = ref<DashboardData | null>(null)

const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function fmtMoney(v: string): string {
  const n = Number(v)
  return Number.isFinite(n) ? money.format(n) : '—'
}

function fmtDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function fetchDash() {
  data.value = await request<DashboardData>('/api/v1/manager/dashboard')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    await fetchDash()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить дашборд')
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (refreshing.value || loading.value) return
  refreshing.value = true
  try {
    await fetchDash()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось обновить данные')
  } finally {
    refreshing.value = false
  }
}

// 4 обычных KPI-плитки (пятая — «Активных импортов» — ссылка на /manager/import).
// Карточки каруселей «Акции»/«Новинки» шлют на поиск по SKU в админ-каталоге.
const kpiTiles = computed(() => {
  if (!data.value) return []
  const k = data.value.kpi
  return [
    { label: 'Заявки сегодня', value: String(k.orders_today), icon: 'heroicons:clipboard-document-list', tone: 'info', to: '/manager/orders' },
    { label: 'Заявки за 7 дней', value: String(k.orders_7d), icon: 'heroicons:inbox-stack', tone: 'info', to: '/manager/orders' },
    { label: 'Выручка за месяц', value: fmtMoney(k.revenue_month), icon: 'heroicons:banknotes', tone: 'success', to: '/manager/orders' },
    { label: 'Новых клиентов за неделю', value: String(k.new_clients_7d), icon: 'heroicons:user-plus', tone: 'warning', to: '/manager/users' },
  ]
})

// Геометрия столбчатого графика «Заявки за 30 дней» (inline SVG).
const chart = computed(() => {
  const items = data.value?.orders_by_day ?? []
  if (!items.length) return null
  const W = 720
  const H = 160 // высота зоны столбцов
  const GAP = 4
  const PAD_LEFT = 38 // левый отступ: место для подписей оси Y + отступ первой точки X
  const max = Math.max(...items.map((i) => i.count), 1) // all-zero → пустая шкала
  const barW = (W - PAD_LEFT - GAP * (items.length - 1)) / items.length
  const bars = items.map((it, idx) => {
    const h = Math.round((it.count / max) * H)
    return {
      x: +(PAD_LEFT + idx * (barW + GAP)).toFixed(2),
      y: H - h,
      w: +barW.toFixed(2),
      h,
      label: `${it.date.split('-').reverse().join('.')}: ${it.count} ${plural(it.count)}`,
      count: it.count,
    }
  })
  // Разреженные подписи оси X — каждая 5-я дата, формат DD.MM.
  const ticks = items
    .map((it, idx) => (idx % 5 === 0 ? { x: +(PAD_LEFT + idx * (barW + GAP) + barW / 2).toFixed(2), text: `${it.date.slice(8, 10)}.${it.date.slice(5, 7)}` } : null))
    .filter((t): t is { x: number; text: string } => t !== null)
  return { W, H, padLeft: PAD_LEFT, bars, ticks, total: items.reduce((s, i) => s + i.count, 0), maxCount: max }
})

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'заявка'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'заявки'
  return 'заявок'
}

function catalogLink(item: { sku: string }): string {
  return `/manager/catalog?q=${encodeURIComponent(item.sku)}`
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Обзор"
      description="Данные агрегируются с задержкой до 60 секунд."
    >
      <template #actions>
        <UiButton variant="outline" size="touch" :disabled="loading || refreshing" @click="refresh">
          <template #leading><Icon name="heroicons:arrow-path" class="size-4" :class="{ 'animate-spin': refreshing }" /></template>
          Обновить
        </UiButton>
      </template>
    </PageHeading>

    <div v-if="error && !data" class="border border-danger/50 bg-danger-soft p-5" role="alert"><p class="text-sm font-semibold">Дашборд недоступен</p><p class="mt-1 text-sm">{{ error }}</p><button type="button" class="btn-outline mt-4 min-h-11" @click="load">Повторить</button></div>
    <template v-else>
      <div v-if="error" class="mb-4 border border-danger/50 bg-danger-soft p-3 text-sm" role="alert">{{ error }}</div>
      <section class="mb-5 border border-border bg-surface" aria-label="Ключевые показатели">
        <header class="border-b border-border bg-surface-2 px-4 py-2 text-xs font-bold uppercase tracking-wide text-ink-muted">Ключевые показатели</header>
        <div class="grid divide-y divide-border sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-5">
          <template v-if="loading"><div v-for="i in 5" :key="i" class="p-4"><div class="skeleton h-3 w-2/3" /><div class="skeleton mt-3 h-7 w-1/2" /></div></template>
          <template v-else-if="data">
            <NuxtLink v-for="k in kpiTiles" :key="k.label" :to="k.to" class="min-h-24 p-4 hover:bg-surface-2"><span class="text-xs text-ink-muted">{{ k.label }}</span><span class="numeric mt-3 block text-2xl font-bold text-action">{{ k.value }}</span></NuxtLink>
            <NuxtLink to="/manager/import" class="min-h-24 p-4 hover:bg-surface-2"><span class="text-xs text-ink-muted">Активных импортов</span><span class="numeric mt-3 block text-2xl font-bold text-action">{{ data.kpi.active_imports }}</span></NuxtLink>
          </template>
        </div>
      </section>

      <section class="mb-5 border border-border bg-surface">
        <header class="flex min-h-12 items-center justify-between border-b border-border bg-surface-2 px-4"><h2 class="text-sm font-bold">Заявки за 30 дней</h2><span v-if="chart" class="numeric text-sm text-ink-muted">Всего: {{ chart.total }}</span></header>
        <div class="p-4"><div v-if="loading" class="skeleton h-44 w-full" /><svg v-else-if="chart" :viewBox="`0 0 ${chart.W} 184`" class="w-full" role="img" aria-label="Заявки за 30 дней"><text x="0" y="5" class="fill-ink-faint" font-size="9">{{ chart.maxCount }}</text><text x="0" :y="chart.H / 2 + 3" class="fill-ink-faint" font-size="9">{{ Math.round(chart.maxCount / 2) }}</text><text x="0" :y="chart.H + 3" class="fill-ink-faint" font-size="9">0</text><line :x1="chart.padLeft" :y1="chart.H" :x2="chart.W" :y2="chart.H" class="stroke-border" /><g class="fill-primary fill-opacity-80"><rect v-for="(b, i) in chart.bars" :key="i" :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="2"><title>{{ b.label }}</title></rect></g><g class="fill-current text-ink-faint" font-size="10" text-anchor="middle"><text v-for="(tick, i) in chart.ticks" :key="i" :x="tick.x" :y="chart.H + 16">{{ tick.text }}</text></g></svg><p v-else class="py-16 text-center text-sm text-ink-muted">Данных за 30 дней нет.</p></div>
      </section>

      <div class="mb-5 grid gap-5 xl:grid-cols-2">
        <section class="border border-border bg-surface"><header class="border-b border-border bg-surface-2 px-4 py-3 text-sm font-bold">Топ-5 товаров за месяц</header><div v-if="loading" class="p-4"><div v-for="i in 5" :key="i" class="skeleton mb-2 h-9" /></div><p v-else-if="!data?.top_products.length" class="p-5 text-sm text-ink-muted">Нет данных за месяц.</p><div v-else class="overflow-x-auto"><table class="w-full text-sm"><thead class="bg-background text-left text-xs text-ink-muted"><tr><th class="px-3 py-2">Артикул</th><th class="px-3 py-2">Наименование</th><th class="px-3 py-2 text-right">Кол-во</th><th class="px-3 py-2 text-right">Выручка, BYN</th></tr></thead><tbody><tr v-for="p in data.top_products.slice(0, 5)" :key="p.product_id" class="border-t border-border"><td class="numeric px-3 py-2.5">{{ p.sku }}</td><td class="max-w-56 truncate px-3 py-2.5">{{ p.name }}</td><td class="numeric px-3 py-2.5 text-right">{{ p.qty }}</td><td class="numeric px-3 py-2.5 text-right">{{ fmtMoney(p.revenue) }}</td></tr></tbody></table></div></section>
        <section class="border border-border bg-surface"><header class="border-b border-border bg-surface-2 px-4 py-3 text-sm font-bold">Топ-5 клиентов за месяц</header><div v-if="loading" class="p-4"><div v-for="i in 5" :key="i" class="skeleton mb-2 h-9" /></div><p v-else-if="!data?.top_clients.length" class="p-5 text-sm text-ink-muted">Нет данных за месяц.</p><div v-else class="overflow-x-auto"><table class="w-full text-sm"><thead class="bg-background text-left text-xs text-ink-muted"><tr><th class="px-3 py-2">Клиент</th><th class="px-3 py-2 text-right">Заявок</th><th class="px-3 py-2 text-right">Выручка, BYN</th></tr></thead><tbody><tr v-for="c in data.top_clients.slice(0, 5)" :key="c.client_id" class="border-t border-border"><td class="max-w-72 truncate px-3 py-2.5">{{ c.name }}</td><td class="numeric px-3 py-2.5 text-right">{{ c.orders }}</td><td class="numeric px-3 py-2.5 text-right">{{ fmtMoney(c.revenue) }}</td></tr></tbody></table></div></section>
      </div>

      <section class="mb-5 border border-border bg-surface"><header class="border-b border-border bg-surface-2 px-4 py-3 text-sm font-bold">Последние заявки</header><div v-if="loading" class="p-4"><div v-for="i in 5" :key="i" class="skeleton mb-2 h-9" /></div><p v-else-if="!data?.recent_orders.length" class="p-5 text-sm text-ink-muted">Заявок пока нет.</p><div v-else class="overflow-x-auto"><table class="w-full text-sm"><thead class="bg-background text-left text-xs text-ink-muted"><tr><th class="px-3 py-2">№</th><th class="px-3 py-2">Дата</th><th class="px-3 py-2">Клиент</th><th class="px-3 py-2">Статус</th><th class="px-3 py-2 text-right">Сумма, BYN</th></tr></thead><tbody><tr v-for="o in data.recent_orders.slice(0, 5)" :key="o.id" class="border-t border-border hover:bg-surface-2"><td class="px-3 py-2.5"><NuxtLink :to="`/manager/orders/${o.id}`" class="numeric font-semibold text-action">{{ formatOrderNumber(o.seq, o.id) }}</NuxtLink></td><td class="px-3 py-2.5 text-ink-muted">{{ fmtDateTime(o.created_at) }}</td><td class="max-w-56 truncate px-3 py-2.5">{{ o.client_name }}</td><td class="px-3 py-2.5"><UiStatusBadge :tone="STATUS_META[o.status].tone" :label="STATUS_META[o.status].label" dot /></td><td class="numeric px-3 py-2.5 text-right">{{ fmtMoney(o.total_amount) }}</td></tr></tbody></table></div></section>

      <div v-if="!loading && (data?.promos?.length || data?.new_arrivals?.length)" class="grid gap-5 xl:grid-cols-2"><ProductCarousel v-if="data?.promos?.length" title="Акции" icon="heroicons:tag" :items="data.promos" :item-link="catalogLink" /><ProductCarousel v-if="data?.new_arrivals?.length" title="Новинки" icon="heroicons:sparkles" :items="data.new_arrivals" :item-link="catalogLink" /></div>
    </template>
  </div>
</template>
