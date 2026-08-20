<script setup lang="ts">
// Дашборд менеджера (фича G, Этап 8). GET /api/v1/manager/dashboard —
// KPI, заявки по дням (30), топы, последние заявки. Кэш на сервере 60 с,
// поэтому кнопка «Обновить» (данные могут отставать ≤60 с).
import type { DashboardData, OrderStatus } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER'] })
useHead({ title: 'Дашборд' })

const { request } = useApi()

// Локальная копия STATUS_META (как в pages/manager/orders/index.vue).
const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

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
const kpiTiles = computed(() => {
  if (!data.value) return []
  const k = data.value.kpi
  return [
    { label: 'Заявки сегодня', value: String(k.orders_today), icon: 'heroicons:clipboard-document-list', tone: 'info' },
    { label: 'Заявки за 7 дней', value: String(k.orders_7d), icon: 'heroicons:inbox-stack', tone: 'info' },
    { label: 'Выручка за месяц, BYN', value: fmtMoney(k.revenue_month), icon: 'heroicons:banknotes', tone: 'success' },
    { label: 'Новых клиентов за 7 дней', value: String(k.new_clients_7d), icon: 'heroicons:user-plus', tone: 'warning' },
  ]
})

// Геометрия столбчатого графика «Заявки за 30 дней» (inline SVG).
const chart = computed(() => {
  const items = data.value?.orders_by_day ?? []
  if (!items.length) return null
  const W = 720
  const H = 160 // высота зоны столбцов
  const GAP = 4
  const max = Math.max(...items.map((i) => i.count), 1) // all-zero → пустая шкала
  const barW = (W - GAP * (items.length - 1)) / items.length
  const bars = items.map((it, idx) => {
    const h = Math.round((it.count / max) * H)
    return {
      x: +(idx * (barW + GAP)).toFixed(2),
      y: H - h,
      w: +barW.toFixed(2),
      h,
      label: `${it.date.split('-').reverse().join('.')}: ${it.count} ${plural(it.count)}`,
      count: it.count,
    }
  })
  // Разреженные подписи оси X — каждая 5-я дата, формат DD.MM.
  const ticks = items
    .map((it, idx) => (idx % 5 === 0 ? { x: +(idx * (barW + GAP) + barW / 2).toFixed(2), text: `${it.date.slice(8, 10)}.${it.date.slice(5, 7)}` } : null))
    .filter((t): t is { x: number; text: string } => t !== null)
  return { W, H, bars, ticks, total: items.reduce((s, i) => s + i.count, 0) }
})

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'заявка'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'заявки'
  return 'заявок'
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Дашборд</h1>
        <p class="text-sm text-ink-muted mt-1">Данные агрегируются с задержкой до 60 секунд</p>
      </div>
      <button class="btn-outline shrink-0" :disabled="loading || refreshing" @click="refresh">
        <Icon
          name="heroicons:arrow-path"
          class="w-4 h-4"
          :class="{ 'animate-spin': refreshing }"
        />
        Обновить
      </button>
    </div>

    <!-- Ошибка: полноэкранная, если данных нет; иначе над контентом -->
    <div v-if="error && !data" class="card p-12 text-center">
      <Icon name="heroicons:exclamation-triangle" class="w-12 h-12 mx-auto mb-3 text-danger" />
      <p class="text-ink-muted mb-4">{{ error }}</p>
      <button class="btn-primary" @click="load">Повторить</button>
    </div>

    <template v-else>
      <div v-if="error" class="badge-danger mb-6">{{ error }}</div>

      <!-- KPI -->
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-5 mb-8">
        <template v-if="loading">
          <div v-for="i in 5" :key="i" class="card p-5">
            <div class="skeleton h-4 w-2/3 mb-3" />
            <div class="skeleton h-8 w-1/2" />
          </div>
        </template>
        <template v-else-if="data">
          <div v-for="k in kpiTiles" :key="k.label" class="card p-5">
            <div class="flex items-center justify-between gap-2 mb-3">
              <span class="text-xs text-ink-muted truncate">{{ k.label }}</span>
              <span :class="`badge-${k.tone} shrink-0`"><Icon :name="k.icon" class="w-3.5 h-3.5" /></span>
            </div>
            <p class="text-2xl font-bold whitespace-nowrap" :title="k.value">{{ k.value }}</p>
          </div>
          <NuxtLink to="/manager/import" class="card p-5 block hover:border-primary transition-colors">
            <div class="flex items-center justify-between gap-2 mb-3">
              <span class="text-xs text-ink-muted truncate">Активных импортов</span>
              <span class="badge-warning shrink-0"><Icon name="heroicons:arrow-up-tray" class="w-3.5 h-3.5" /></span>
            </div>
            <p class="text-2xl font-bold">{{ data.kpi.active_imports }}</p>
          </NuxtLink>
        </template>
      </div>

      <!-- График заявок за 30 дней -->
      <div class="card p-6 mb-8">
        <h3 class="font-semibold mb-4">Заявки за 30 дней</h3>
        <div v-if="loading" class="skeleton h-44 w-full" />
        <div v-else-if="chart">
          <svg :viewBox="`0 0 ${chart.W} 184`" class="w-full" role="img" aria-label="Заявки за 30 дней">
            <!-- Базовая линия -->
            <line x1="0" :y1="chart.H" :x2="chart.W" :y2="chart.H" class="stroke-border" stroke-width="1" />
            <g class="fill-primary fill-opacity-80">
              <rect v-for="(b, i) in chart.bars" :key="i" :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="2">
                <title>{{ b.label }}</title>
              </rect>
            </g>
            <g class="fill-current text-ink-faint" font-size="10" text-anchor="middle">
              <text v-for="(t, i) in chart.ticks" :key="i" :x="t.x" :y="chart.H + 16">{{ t.text }}</text>
            </g>
          </svg>
        </div>
        <div v-else class="h-44 flex items-center justify-center text-ink-faint text-sm">Нет данных</div>
        <p v-if="chart && chart.total === 0" class="text-xs text-ink-faint mt-2 text-center">За последние 30 дней заявок не было</p>
      </div>

      <!-- Топы -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-8">
        <div class="card overflow-hidden">
          <h3 class="font-semibold px-6 py-4">Топ-5 товаров за месяц</h3>
          <div v-if="loading" class="px-6 pb-6">
            <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
          </div>
          <div v-else-if="!data?.top_products.length" class="px-6 pb-6 text-sm text-ink-muted text-center">
            Нет данных за месяц
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-ink-muted text-left bg-canvas">
                  <th class="px-6 py-2.5 font-medium">Артикул</th>
                  <th class="px-4 py-2.5 font-medium">Наименование</th>
                  <th class="px-4 py-2.5 font-medium text-right">Кол-во</th>
                  <th class="px-6 py-2.5 font-medium text-right">Выручка, BYN</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in data.top_products.slice(0, 5)" :key="p.product_id" class="border-t border-border">
                  <td class="px-6 py-2.5 font-mono text-xs whitespace-nowrap">{{ p.sku }}</td>
                  <td class="px-4 py-2.5 max-w-56 truncate" :title="p.name">{{ p.name }}</td>
                  <td class="px-4 py-2.5 text-right">{{ p.qty }}</td>
                  <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ fmtMoney(p.revenue) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card overflow-hidden">
          <h3 class="font-semibold px-6 py-4">Топ-5 клиентов за месяц</h3>
          <div v-if="loading" class="px-6 pb-6">
            <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
          </div>
          <div v-else-if="!data?.top_clients.length" class="px-6 pb-6 text-sm text-ink-muted text-center">
            Нет данных за месяц
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-ink-muted text-left bg-canvas">
                  <th class="px-6 py-2.5 font-medium">Клиент</th>
                  <th class="px-4 py-2.5 font-medium text-right">Заявок</th>
                  <th class="px-6 py-2.5 font-medium text-right">Выручка, BYN</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in data.top_clients.slice(0, 5)" :key="c.client_id" class="border-t border-border">
                  <td class="px-6 py-2.5 max-w-72 truncate" :title="c.name">{{ c.name }}</td>
                  <td class="px-4 py-2.5 text-right">{{ c.orders }}</td>
                  <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ fmtMoney(c.revenue) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Последние заявки -->
      <div class="card overflow-hidden">
        <h3 class="font-semibold px-6 py-4">Последние заявки</h3>
        <div v-if="loading" class="px-6 pb-6">
          <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
        </div>
        <div v-else-if="!data?.recent_orders.length" class="px-6 pb-6 text-sm text-ink-muted text-center">
          Заявок пока нет
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-canvas">
                <th class="px-6 py-2.5 font-medium">№</th>
                <th class="px-4 py-2.5 font-medium">Дата</th>
                <th class="px-4 py-2.5 font-medium">Клиент</th>
                <th class="px-4 py-2.5 font-medium">Статус</th>
                <th class="px-6 py-2.5 font-medium text-right">Сумма, BYN</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="o in data.recent_orders.slice(0, 5)"
                :key="o.id"
                class="border-t border-border hover:bg-canvas/60"
              >
                <td class="px-6 py-2.5">
                  <NuxtLink
                    :to="`/manager/orders/${o.id}`"
                    class="font-medium text-primary hover:underline whitespace-nowrap"
                  >Заявка {{ o.id.slice(0, 8) }}</NuxtLink>
                </td>
                <td class="px-4 py-2.5 text-ink-muted whitespace-nowrap">{{ fmtDateTime(o.created_at) }}</td>
                <td class="px-4 py-2.5 max-w-56 truncate" :title="o.client_name">{{ o.client_name }}</td>
                <td class="px-4 py-2.5"><span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span></td>
                <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ fmtMoney(o.total_amount) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
