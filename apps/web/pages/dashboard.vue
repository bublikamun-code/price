<script setup lang="ts">
// «Моя аналитика» — сводка клиента (route /dashboard): KPI, график заявок за 30 дней,
// статусы, топ товаров, последние/активные заявки, изменения цен в избранном, акции и новинки.
// GET /api/v1/dashboard (аналог /api/v1/manager/dashboard для клиента, кэш ~60 с).
import type { OrderStatus, OrdersByDayItem } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Моя аналитика' })

const { request } = useApi()
const auth = useAuth()
const { thumbOf } = useProductPhoto()

// Маппинг статуса → бейдж, как на /orders.
const STATUS_META: Record<OrderStatus, { label: string; cls: string }> = {
  NEW: { label: 'Новая', cls: 'badge-info' },
  IN_PROGRESS: { label: 'В работе', cls: 'badge-info' },
  SHIPPED: { label: 'Отгружена', cls: 'badge-warning' },
  COMPLETED: { label: 'Завершена', cls: 'badge-success' },
  CANCELLED: { label: 'Отменена', cls: 'badge-danger' },
}

// Локальные типы ответа GET /api/v1/dashboard (см. types/api.ts для менеджерского аналога).
interface ClientDashboardKpi {
  orders_total: number
  orders_this_month: number
  total_spent_byn: string
  avg_order_byn: string
}

interface ClientStatusCount {
  status: OrderStatus
  count: number
}

interface ClientTopProduct {
  product_id: string
  sku: string
  name: string
  qty: number
  revenue_byn: string // BYN
}

// seq может отсутствовать (бэкенд не отдаёт) — formatOrderNumber падает обратно на id.
type ClientRecentOrder = {
  id: string
  created_at: string
  status: OrderStatus
  total_amount: string // BYN
  seq?: number | null
}

interface ClientActiveOrder {
  id: string
  number: string
  created_at: string
  status: OrderStatus
  total_amount: string // BYN
}

interface ClientPriceChange {
  product_id: string
  sku: string
  name: string
  photo_key: string | null
  new_client_price: string
  old_client_price: string
  currency: string
  category: 'down' | 'up' | 'new'
  delta_percent: string
}

interface ClientNewArrival {
  id: string
  sku: string
  name: string
  photo_key: string | null
  client_price: string
  currency: string
  has_discount: boolean
}

interface ClientDashboardData {
  kpi: ClientDashboardKpi
  orders_by_day: OrdersByDayItem[]
  status_counts: ClientStatusCount[]
  top_products: ClientTopProduct[]
  recent_orders: ClientRecentOrder[]
  active_orders: ClientActiveOrder[]
  favorite_price_changes: ClientPriceChange[]
  new_arrivals: ClientNewArrival[]
  // Товары со скидкой клиента (карусель «Акции»). Поле новое — бэкенд может ещё не отдавать.
  promos?: ClientNewArrival[]
  quick_actions: { repeat_order_id: string | null }
}

const loading = ref(true)
const error = ref('')
const data = ref<ClientDashboardData | null>(null)
const repeating = ref(false)

const kpiTiles = computed(() => {
  if (!data.value) return []
  const k = data.value.kpi
  return [
    { label: 'Всего заявок', value: String(k.orders_total), icon: 'heroicons:clipboard-document-list', tone: 'info' },
    { label: 'Заявок в этом месяце', value: String(k.orders_this_month), icon: 'heroicons:calendar', tone: 'info' },
    { label: 'Общая сумма покупок', value: formatMoney(k.total_spent_byn, 'BYN'), icon: 'heroicons:banknotes', tone: 'success' },
    { label: 'Средний чек', value: formatMoney(k.avg_order_byn, 'BYN'), icon: 'heroicons:calculator', tone: 'warning' },
  ]
})

// Геометрия столбчатого графика «Заявки за 30 дней» (inline SVG).
const chart = computed(() => {
  const items = data.value?.orders_by_day ?? []
  if (!items.length) return null
  const W = 720
  const H = 160 // высота зоны столбцов
  const GAP = 4
  const PAD_LEFT = 12 // левый отступ области построения, чтобы первая подпись оси X не резалась
  const max = Math.max(...items.map(i => i.count), 1) // all-zero → пустая шкала
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
  return { W, H, padLeft: PAD_LEFT, bars, ticks, total: items.reduce((s, i) => s + i.count, 0) }
})

function plural(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'заявка'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'заявки'
  return 'заявок'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await request<ClientDashboardData>('/api/v1/dashboard')
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить данные')
  } finally {
    loading.value = false
  }
}

// «Повторить последнюю заявку»: POST /orders/{id}/repeat → корзина → /cart.
async function repeatLast() {
  const id = data.value?.quick_actions.repeat_order_id
  if (!id || repeating.value) return
  repeating.value = true
  try {
    await request(`/api/v1/orders/${id}/repeat`, { method: 'POST' })
    await navigateTo('/cart')
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось повторить заявку')
  } finally {
    repeating.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Моя аналитика</h1>
      <p class="text-sm text-ink-muted mt-1">Данные обновляются с задержкой до 60 секунд</p>
    </div>

    <ManagerCard :manager="auth.user?.manager" class="mb-6" />

    <!-- Ошибка: полноэкранная, если данных нет; иначе над контентом -->
    <div v-if="error && !data" class="card p-12 text-center">
      <Icon name="heroicons:exclamation-triangle" class="w-12 h-12 mx-auto mb-3 text-danger" />
      <p class="text-ink-muted mb-4">{{ error }}</p>
      <button class="btn-primary" @click="load">Повторить</button>
    </div>

    <template v-else>
      <div v-if="error" class="badge-danger mb-6">{{ error }}</div>

      <!-- Быстрые действия -->
      <div class="card p-5 mb-8">
        <h3 class="font-semibold mb-4">Быстрые действия</h3>
        <div v-if="loading" class="flex flex-wrap gap-3">
          <div class="skeleton h-10 w-40" />
          <div class="skeleton h-10 w-48" />
        </div>
        <div v-else class="flex flex-wrap gap-3">
          <NuxtLink to="/bulk-add" class="btn-primary inline-flex items-center gap-2">
            <Icon name="heroicons:plus" class="w-4 h-4" /> Массовое добавление
          </NuxtLink>
          <button
            class="btn-outline inline-flex items-center gap-2"
            :disabled="!data?.quick_actions.repeat_order_id || repeating"
            @click="repeatLast"
          >
            <span v-if="repeating" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            <Icon v-else name="heroicons:arrow-path" class="w-4 h-4" />
            Повторить последнюю заявку
          </button>
        </div>
      </div>

      <!-- KPI -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
        <template v-if="loading">
          <div v-for="i in 4" :key="i" class="card p-4 sm:p-5">
            <div class="skeleton h-4 w-2/3 mb-3" />
            <div class="skeleton h-8 w-1/2" />
          </div>
        </template>
        <template v-else-if="data">
          <!-- min-w-0 + break-words: длинные суммы («3 690,00 BYN») не вылезают за карточку на 359px -->
          <div v-for="k in kpiTiles" :key="k.label" class="card p-4 sm:p-5 min-w-0">
            <div class="flex items-center justify-between gap-2 mb-3">
              <span class="text-xs sm:text-sm text-ink-muted line-clamp-2 pr-1">{{ k.label }}</span>
              <span :class="`badge-${k.tone} shrink-0`"><Icon :name="k.icon" class="w-3.5 h-3.5" /></span>
            </div>
            <p class="text-xl sm:text-3xl font-bold break-words" :title="k.value">{{ k.value }}</p>
          </div>
        </template>
      </div>

      <!-- График + статусы -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-8">
        <div class="card p-6 lg:col-span-2">
          <h3 class="font-semibold mb-4">Заявки за 30 дней</h3>
          <div v-if="loading" class="skeleton h-44 w-full" />
          <div v-else-if="chart">
            <svg :viewBox="`0 0 ${chart.W} 184`" class="w-full" role="img" aria-label="Заявки за 30 дней">
              <!-- Базовая линия -->
              <line :x1="chart.padLeft" :y1="chart.H" :x2="chart.W" :y2="chart.H" class="stroke-border" stroke-width="1" />
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

        <div class="card p-6">
          <h3 class="font-semibold mb-4">Статусы заявок</h3>
          <div v-if="loading" class="space-y-3">
            <div v-for="i in 5" :key="i" class="skeleton h-8 w-full" />
          </div>
          <EmptyState
            v-else-if="!data?.status_counts.length"
            icon="heroicons:clipboard-document-list"
            title="Заявок пока нет"
            description="После оформления здесь появится статистика."
          />
          <ul v-else class="space-y-2">
            <li v-for="s in data.status_counts" :key="s.status" class="flex items-center justify-between text-sm py-1.5 border-b border-border last:border-0">
              <span :class="STATUS_META[s.status]?.cls ?? 'badge-info'">{{ STATUS_META[s.status]?.label ?? s.status }}</span>
              <span class="font-semibold">{{ s.count }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- Топ-5 товаров: полная ширина -->
      <div class="card overflow-hidden mb-8">
        <h3 class="font-semibold px-6 py-4">Топ-5 товаров</h3>
        <div v-if="loading" class="px-6 pb-6">
          <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
        </div>
        <EmptyState
          v-else-if="!data?.top_products.length"
          icon="heroicons:shopping-bag"
          title="Пока нет данных"
          description="Товары из ваших заявок появятся в этом списке."
        />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-6 py-2.5 font-medium">Артикул</th>
                <th class="px-4 py-2.5 font-medium">Наименование</th>
                <th class="px-4 py-2.5 font-medium text-right whitespace-nowrap">Кол-во</th>
                <th class="px-6 py-2.5 font-medium text-right whitespace-nowrap">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in data.top_products" :key="p.product_id" class="border-t border-border hover:bg-canvas/60">
                <td class="px-6 py-2.5 font-mono text-xs whitespace-nowrap">{{ p.sku }}</td>
                <td class="px-4 py-2.5 max-w-56 truncate" :title="p.name">{{ p.name }}</td>
                <td class="px-4 py-2.5 text-right">{{ p.qty }}</td>
                <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ formatMoney(p.revenue_byn, 'BYN') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Последние заявки: полная ширина -->
      <div class="card overflow-hidden mb-8">
        <h3 class="font-semibold px-6 py-4">Последние заявки</h3>
        <div v-if="loading" class="px-6 pb-6">
          <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
        </div>
        <EmptyState
          v-else-if="!data?.recent_orders.length"
          icon="heroicons:clock"
          title="Заявок пока нет"
          description="История ваших заявок будет здесь."
        />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                <th class="px-6 py-2.5 font-medium">№</th>
                <th class="px-4 py-2.5 font-medium">Дата</th>
                <th class="px-4 py-2.5 font-medium">Статус</th>
                <th class="px-6 py-2.5 font-medium text-right">Сумма</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in data.recent_orders" :key="o.id" class="border-t border-border hover:bg-canvas/60">
                <td class="px-6 py-2.5">
                  <NuxtLink :to="`/orders/${o.id}`" class="font-medium text-primary hover:underline whitespace-nowrap">
                    {{ formatOrderNumber(o.seq, o.id) }}
                  </NuxtLink>
                </td>
                <td class="px-4 py-2.5 text-ink-muted whitespace-nowrap">{{ formatDate(o.created_at) }}</td>
                <td class="px-4 py-2.5"><span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span></td>
                <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ formatMoney(o.total_amount, 'BYN') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Заявки в работе + изменения цен избранного: ряд из двух колонок -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-8">
        <div class="card overflow-hidden">
          <h3 class="font-semibold px-6 py-4">Заявки в работе</h3>
          <div v-if="loading" class="px-6 pb-6">
            <div v-for="i in 5" :key="i" class="skeleton h-10 w-full mb-2 last:mb-0" />
          </div>
          <EmptyState
            v-else-if="!data?.active_orders.length"
            icon="heroicons:arrow-path"
            title="Нет заявок в работе"
            description="Активные заявки отобразятся после оформления."
          />
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                  <th class="px-6 py-2.5 font-medium">№</th>
                  <th class="px-4 py-2.5 font-medium">Дата</th>
                  <th class="px-4 py-2.5 font-medium">Статус</th>
                  <th class="px-6 py-2.5 font-medium text-right">Сумма</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="o in data.active_orders" :key="o.id" class="border-t border-border hover:bg-canvas/60">
                  <td class="px-6 py-2.5">
                    <NuxtLink :to="`/orders/${o.id}`" class="font-medium text-primary hover:underline whitespace-nowrap">
                      {{ o.number }}
                    </NuxtLink>
                  </td>
                  <td class="px-4 py-2.5 text-ink-muted whitespace-nowrap">{{ formatDate(o.created_at) }}</td>
                  <td class="px-4 py-2.5"><span :class="STATUS_META[o.status].cls">{{ STATUS_META[o.status].label }}</span></td>
                  <td class="px-6 py-2.5 text-right whitespace-nowrap">{{ formatMoney(o.total_amount, 'BYN') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card overflow-hidden">
          <h3 class="font-semibold px-6 py-4">Изменения цен в избранном</h3>
          <div v-if="loading" class="px-6 pb-6 space-y-3">
            <div v-for="i in 3" :key="i" class="skeleton h-16 w-full" />
          </div>
          <EmptyState
            v-else-if="!data?.favorite_price_changes.length"
            icon="heroicons:tag"
            title="Изменений цен нет"
            description="Добавьте товары в избранное, чтобы следить за ценами."
          />
          <div v-else class="px-6 pb-6 space-y-4">
            <NuxtLink v-for="p in data.favorite_price_changes" :key="p.product_id" :to="`/catalog/${p.sku}`" class="flex gap-3 group">
              <div class="w-16 h-16 shrink-0 bg-canvas rounded-card flex items-center justify-center overflow-hidden">
                <img
                  v-if="thumbOf(p.photo_key)"
                  :src="thumbOf(p.photo_key)!"
                  :alt="p.name"
                  class="w-full h-full object-contain"
                  loading="lazy"
                >
                <Icon v-else name="heroicons:photo" class="w-6 h-6 text-ink-faint" />
              </div>
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium line-clamp-2 group-hover:text-primary">{{ p.name }}</p>
                <p class="text-xs text-ink-faint mb-1">Артикул: {{ p.sku }}</p>
                <div class="flex items-baseline gap-2 flex-wrap">
                  <span class="text-sm font-bold">{{ formatMoney(p.new_client_price, p.currency) }}</span>
                  <template v-if="p.category !== 'new'">
                    <span class="text-xs text-ink-faint line-through">{{ formatMoney(p.old_client_price, p.currency) }}</span>
                    <span :class="[p.category === 'down' ? 'text-success' : 'text-danger', 'text-xs font-medium']">
                      {{ Number(p.delta_percent) > 0 ? '+' : '' }}{{ formatPercent(p.delta_percent) }}
                    </span>
                  </template>
                  <span v-else class="text-xs badge-info">Новая цена</span>
                </div>
              </div>
            </NuxtLink>
          </div>
        </div>

      </div>
    </template>
  </div>
</template>
