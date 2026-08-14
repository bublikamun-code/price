<script setup lang="ts">
// Детальная карточка товара. См. SITEMAP.md §6.
// Реальные данные: GET /catalog/products/{sku}, /catalog/products/{sku}/price-history,
// соседи по серии — GET /catalog/products?series=<id>.
// Корзина/избранное скрыты — бэкенд появится на Этапе 6.
import type {
  CatalogPage,
  PriceHistoryItem,
  ProductCard,
  ProductDetail,
} from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const { request } = useApi()
const { photoOf } = useProductPhoto()

const sku = computed(() => String(route.params.sku))

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const product = ref<ProductDetail | null>(null)
const history = ref<PriceHistoryItem[]>([])
const siblings = ref<ProductCard[]>([])
const lightbox = ref(false)

useHead({ title: computed(() => product.value?.name || 'Товар') })

const STOCK_META: Record<string, { label: string; cls: string }> = {
  IN_STOCK: { label: 'В наличии', cls: 'badge-success' },
  PREORDER: { label: 'Под заказ', cls: 'badge-warning' },
  ARCHIVED: { label: 'Архив', cls: 'badge-danger' },
}

function rateSourceLabel(s: string | null | undefined): string {
  switch (s) {
    case 'BYN': return 'Без конвертации (BYN)'
    case 'FIXED': return 'По договору'
    case 'NBRB': return 'Текущий курс НБ РБ'
    default: return s || '—'
  }
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU')
}

// Характеристики без служебного photo_url
const attrEntries = computed<{ label: string; value: string }[]>(() => {
  const a = product.value?.attributes || {}
  return Object.entries(a)
    .filter(([k]) => k !== 'photo_url')
    .map(([k, v]) => ({ label: k, value: String(v) }))
})

async function loadProduct() {
  try {
    product.value = await request<ProductDetail>(
      `/api/v1/catalog/products/${encodeURIComponent(sku.value)}`,
      { query: { price_calc_mode: 'fixed' } },
    )
  } catch (e) {
    if (getErrorStatus(e) === 404) {
      notFound.value = true
    } else {
      error.value = getErrorMessage(e, 'Не удалось загрузить товар')
    }
    throw e
  }
}

async function loadHistory() {
  try {
    history.value = await request<PriceHistoryItem[]>(
      `/api/v1/catalog/products/${encodeURIComponent(sku.value)}/price-history`,
    )
  } catch {
    history.value = []
  }
}

async function loadSiblings() {
  const seriesId = product.value?.series?.id
  if (!seriesId) return
  try {
    const res = await request<CatalogPage>('/api/v1/catalog/products', {
      query: { series: seriesId, per_page: 10 },
    })
    siblings.value = res.data.filter((p) => p.sku !== sku.value)
  } catch {
    siblings.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  product.value = null
  history.value = []
  siblings.value = []
  lightbox.value = false
  try {
    await loadProduct()
    if (product.value) await Promise.allSettled([loadHistory(), loadSiblings()])
  } catch {
    // ошибка уже зафиксирована в loadProduct
  } finally {
    loading.value = false
  }
}

// SVG-спарклайн истории цены (без зависимостей)
const chart = computed(() => {
  const pts = [...history.value].sort(
    (a, b) => +new Date(a.changed_at) - +new Date(b.changed_at),
  )
  if (pts.length < 2) return null
  const W = 600
  const H = 200
  const PAD = 24
  const values: number[] = []
  pts.forEach((p) => {
    values.push(p.base_price)
    if (p.override_price != null) values.push(p.override_price)
  })
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (min === max) {
    min -= 1
    max += 1
  }
  const span = max - min
  const xStep = (W - PAD * 2) / (pts.length - 1)
  const y = (val: number) => H - PAD - ((val - min) / span) * (H - PAD * 2)

  const base = pts.map((p, i) => `${PAD + i * xStep},${y(p.base_price)}`).join(' ')

  const overrideCoords = pts
    .map((p, i) =>
      p.override_price != null ? `${PAD + i * xStep},${y(p.override_price)}` : null,
    )
    .filter((c): c is string => c !== null)
  const override = overrideCoords.length >= 2 ? overrideCoords.join(' ') : ''

  return {
    base,
    override,
    first: pts[0].changed_at,
    last: pts[pts.length - 1].changed_at,
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && lightbox.value) lightbox.value = false
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div>
    <!-- Хлебные крошки -->
    <nav class="flex flex-wrap items-center gap-2 text-sm text-ink-muted mb-6">
      <NuxtLink to="/catalog" class="hover:text-primary">Каталог</NuxtLink>
      <template v-if="product">
        <template v-if="product.brand">
          <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
          <span>{{ product.brand.name }}</span>
        </template>
        <template v-if="product.series">
          <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
          <span>{{ product.series.name }}</span>
        </template>
        <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
        <span class="text-ink">{{ product.name }}</span>
      </template>
    </nav>

    <!-- Skeleton -->
    <div v-if="loading" class="grid lg:grid-cols-2 gap-8">
      <div class="card p-5">
        <div class="skeleton aspect-square mb-4 rounded-card"/>
      </div>
      <div class="space-y-4">
        <div class="skeleton h-4 w-1/4"/>
        <div class="skeleton h-8 w-3/4"/>
        <div class="skeleton h-24 w-full"/>
        <div class="skeleton h-10 w-1/3"/>
      </div>
    </div>

    <!-- 404 -->
    <div v-else-if="notFound" class="card p-12 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="text-ink-muted mb-4">Товар не найден</p>
      <NuxtLink to="/catalog" class="btn-primary">Вернуться в каталог</NuxtLink>
    </div>

    <!-- Ошибка -->
    <div v-else-if="error" class="card p-8 text-center">
      <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
      <div>
        <button class="btn-primary" @click="load">Повторить</button>
      </div>
    </div>

    <!-- Карточка товара -->
    <div v-else-if="product">
      <div class="grid lg:grid-cols-2 gap-8">
        <!-- Фото -->
        <div>
          <div class="card aspect-square overflow-hidden bg-surface-2 flex items-center justify-center">
            <img
              v-if="photoOf(product)"
              :src="photoOf(product)!"
              :alt="product.name"
              class="w-full h-full object-cover cursor-zoom-in"
              @click="lightbox = true"
            >
            <Icon v-else name="heroicons:photo" class="w-20 h-20 text-ink-faint" />
          </div>
          <!-- Миниатюры (одно фото → одна) -->
          <div v-if="photoOf(product)" class="flex gap-3 mt-3">
            <div class="w-20 h-20 rounded-card overflow-hidden border-2 border-primary bg-surface-2">
              <img :src="photoOf(product)!" :alt="product.name" class="w-full h-full object-cover" >
            </div>
          </div>
        </div>

        <!-- Инфо -->
        <div>
          <p class="text-sm text-ink-muted mb-1">Артикул: {{ product.sku }}</p>
          <h1 class="text-2xl font-display font-bold mb-3">{{ product.name }}</h1>

          <div class="flex flex-wrap items-center gap-2 mb-5">
            <span v-if="product.brand" class="badge-info">{{ product.brand.name }}</span>
            <span v-if="product.series" class="chip bg-surface border border-border">
              {{ product.series.name }}
            </span>
            <span :class="STOCK_META[product.stock_status]?.cls || 'badge-info'">
              {{ STOCK_META[product.stock_status]?.label || product.stock_status }}
            </span>
          </div>

          <!-- Цена -->
          <div class="card p-5 mb-5">
            <div class="flex items-baseline gap-2 flex-wrap">
              <template v-if="product.has_discount">
                <span class="text-3xl font-bold text-primary">{{ product.client_price }} {{ product.currency }}</span>
                <span class="text-ink-muted line-through">{{ product.retail_price }} {{ product.currency }}</span>
              </template>
              <template v-else>
                <span class="text-3xl font-bold">{{ product.retail_price }} {{ product.currency }}</span>
              </template>
            </div>
            <p class="text-xs text-ink-faint mt-2">
              Источник курса: {{ rateSourceLabel(product.rate_source) }}
            </p>
            <div v-if="product.override_price != null" class="mt-3">
              <span class="badge-info">
                Фиксированная цена: {{ product.override_price }} {{ product.currency }}
              </span>
            </div>
          </div>

          <!-- Характеристики -->
          <div v-if="attrEntries.length">
            <h3 class="font-semibold mb-3">Характеристики</h3>
            <dl class="card divide-y divide-border">
              <div
                v-for="row in attrEntries"
                :key="row.label"
                class="flex justify-between gap-4 px-4 py-2.5 text-sm"
              >
                <dt class="text-ink-muted capitalize">{{ row.label }}</dt>
                <dd class="font-medium text-right break-all">{{ row.value }}</dd>
              </div>
            </dl>
          </div>
        </div>
      </div>

      <!-- График истории цены -->
      <div v-if="history.length >= 2 && chart" class="card p-6 mt-8">
        <h3 class="font-semibold mb-4">История цены</h3>
        <svg v-if="chart" :viewBox="`0 0 600 200`" class="w-full" preserveAspectRatio="none">
          <!-- Базовая цена -->
          <polyline
            :points="chart.base"
            fill="none"
            stroke="currentColor"
            class="text-primary"
            stroke-width="2"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
          <!-- Фикс. цена -->
          <polyline
            v-if="chart.override"
            :points="chart.override"
            fill="none"
            stroke="currentColor"
            class="text-warning"
            stroke-width="2"
            stroke-dasharray="5 4"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
        </svg>
        <div class="flex items-center justify-between mt-2 text-xs text-ink-faint">
          <span>{{ formatDate(chart.first) }}</span>
          <div class="flex items-center gap-4">
            <span class="flex items-center gap-1.5">
              <span class="w-3 h-0.5 bg-primary"/> Базовая
            </span>
            <span v-if="chart.override" class="flex items-center gap-1.5">
              <span class="w-3 h-0.5 bg-warning"/> Фиксированная
            </span>
          </div>
          <span>{{ formatDate(chart.last) }}</span>
        </div>
      </div>

      <!-- Соседи по серии -->
      <div v-if="siblings.length" class="mt-8">
        <h3 class="font-semibold mb-4">
          Похожие товары<template v-if="product.series"> серии {{ product.series.name }}</template>
        </h3>
        <div class="flex gap-4 overflow-x-auto pb-2">
          <NuxtLink
            v-for="s in siblings"
            :key="s.id"
            :to="`/catalog/${s.sku}`"
            class="card card-hover p-4 shrink-0 w-56 flex flex-col"
          >
            <div class="aspect-square bg-canvas rounded-card mb-3 flex items-center justify-center overflow-hidden">
              <img
                v-if="photoOf(s)"
                :src="photoOf(s)!"
                :alt="s.name"
                loading="lazy"
                class="w-full h-full object-contain"
              >
              <Icon v-else name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
            </div>
            <span v-if="s.brand" class="badge-info self-start mb-1.5">{{ s.brand.name }}</span>
            <h4 class="font-medium text-sm line-clamp-2 mb-1">{{ s.name }}</h4>
            <p class="text-xs text-ink-faint mb-2">{{ s.sku }}</p>
            <div class="mt-auto">
              <span class="text-base font-bold text-primary">
                {{ s.has_discount ? s.client_price : s.retail_price }} {{ s.currency }}
              </span>
            </div>
          </NuxtLink>
        </div>
      </div>
    </div>

    <!-- Lightbox -->
    <div
      v-if="lightbox && product && photoOf(product)"
      class="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-8"
      @click.self="lightbox = false"
    >
      <img
        :src="photoOf(product)!"
        :alt="product.name"
        class="max-h-[90vh] max-w-[90vw] object-contain"
      >
      <button class="absolute top-4 right-4 btn-ghost p-2 text-white" @click="lightbox = false">
        <Icon name="heroicons:x-mark" class="w-6 h-6" />
      </button>
    </div>
  </div>
</template>
