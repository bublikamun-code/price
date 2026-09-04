<script setup lang="ts">
// Каталог / Прайс-лист — ключевая страница (SITEMAP.md §6).
// Реальные данные: GET /api/v1/catalog/products, /catalog/filters.
// Экспорт каталога под текущие фильтры: POST /catalog/export + опрос статуса.
import type { CatalogPage, ExportFormat, ExportJobOut, ExportStartOut, FiltersOut, ProductCard } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Каталог' })

const { request } = useApi()
const route = useRoute()

// Избранное: сердечко в карточке (ленивая загрузка списка — внутри isFav/toggle).
const favorites = useFavorites()
async function toggleFav(sku: string) {
  try {
    await favorites.toggle(sku)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось обновить избранное')
  }
}

type Sort = 'name' | '-name' | 'price' | '-price' | 'sku'
const PER_PAGE = 12

const sortOptions = [
  { value: 'name', label: 'Название А→Я' },
  { value: '-name', label: 'Название Я→А' },
  { value: 'price', label: 'Цена ↑' },
  { value: '-price', label: 'Цена ↓' },
  { value: 'sku', label: 'Артикул' },
]
const stockOptions = [
  { value: '', label: 'Любое' },
  { value: 'IN_STOCK', label: 'В наличии' },
  { value: 'PREORDER', label: 'Под заказ' },
]

const loading = ref(true)
const error = ref('')
const products = ref<ProductCard[]>([])
const total = ref(0)
const filters = ref<FiltersOut>({ brands: [], series: [], stock: [] })

// Корзина: добавление товара прямо из карточки.
const cart = useCart()
const qtyMap = reactive<Record<string, number>>({})
const addingSku = ref<string | null>(null)
const addedSku = ref<string | null>(null)
function getQty(sku: string): number {
  return qtyMap[sku] ?? 1
}
function setQty(sku: string, v: number) {
  qtyMap[sku] = Math.max(1, Math.floor(v) || 1)
}
async function addToCart(p: ProductCard) {
  if (addingSku.value) return
  addingSku.value = p.sku
  try {
    await cart.add({ sku: p.sku, quantity: getQty(p.sku) })
    addedSku.value = p.sku
    setTimeout(() => {
      if (addedSku.value === p.sku) addedSku.value = null
    }, 1500)
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось добавить в корзину')
  } finally {
    addingSku.value = null
  }
}

// фильтры / состояние
const q = ref((route.query.q as string) || '')
const selectedBrands = ref<string[]>([])
const selectedSeries = ref<string[]>([])
// Инициализация бренда/серии из URL (/catalog?brand=<id> / ?series=<id>,
// ссылки из хлебных крошек и чипов карточки товара)
function idsFromQuery(key: string): string[] {
  const v = route.query[key]
  if (!v) return []
  return Array.isArray(v) ? v.map(String) : [String(v)]
}
selectedBrands.value = idsFromQuery('brand')
selectedSeries.value = idsFromQuery('series')
const selectedStock = ref<string>('') // '' | IN_STOCK | PREORDER
const sort = ref<Sort>('name')
const page = ref(1)
const priceMode = ref<'discount' | 'retail'>('discount')
const viewMode = ref<'grid' | 'list'>('grid')

// Видимость панели фильтров:
// - десктоп (lg+): aside тогглится кнопкой, по умолчанию показан
// - мобильный (<lg): aside открыт только как шторка (drawerOpen), по умолчанию закрыт
const desktopFiltersVisible = ref(true)
const drawerOpen = ref(false)
function toggleFilters() {
  if (window.innerWidth >= 1024) desktopFiltersVisible.value = !desktopFiltersVisible.value
  else drawerOpen.value = true
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

// Сворачиваемые списки в фильтрах: длинные перечни брендов/серий режем
// до FILTER_COLLAPSED штук с кнопкой «Показать все».
const FILTER_COLLAPSED = 6
const expandedFilters = reactive<Record<string, boolean>>({})
function visibleFilterItems<T extends { id: string }>(items: T[], key: string): T[] {
  return expandedFilters[key] ? items : items.slice(0, FILTER_COLLAPSED)
}
function hiddenFilterCount<T extends { id: string }>(items: T[], key: string): number {
  return expandedFilters[key] ? 0 : Math.max(0, items.length - FILTER_COLLAPSED)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [catalog, f] = await Promise.all([
      request<CatalogPage>('/api/v1/catalog/products', {
        query: {
          q: q.value || undefined,
          brand: selectedBrands.value.length ? selectedBrands.value : undefined,
          series: selectedSeries.value.length ? selectedSeries.value : undefined,
          stock: selectedStock.value || undefined,
          sort: sort.value,
          page: page.value,
          per_page: PER_PAGE,
        },
      }),
      request<FiltersOut>('/api/v1/catalog/filters'),
    ])
    products.value = catalog.data
    total.value = catalog.meta.total
    filters.value = f
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить каталог')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  load()
}
function resetFilters() {
  q.value = ''
  selectedBrands.value = []
  selectedSeries.value = []
  selectedStock.value = ''
  sort.value = 'name'
  page.value = 1
  load()
}
function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// Экспорт каталога (§16 п.16): Celery-задача собирает файл, статус опрашиваем.
const EXPORT_POLL_MS = 2000
const EXPORT_MAX_POLLS = 60
const exporting = ref(false)
const exportError = ref('')
const exportMenuOpen = ref(false)
let exportTimer: ReturnType<typeof setTimeout> | null = null

async function startExport(format: ExportFormat) {
  exportMenuOpen.value = false
  if (exporting.value) return
  exporting.value = true
  exportError.value = ''
  try {
    const started = await request<ExportStartOut>('/api/v1/catalog/export', {
      method: 'POST',
      query: {
        format,
        q: q.value || undefined,
        brand: selectedBrands.value.length ? selectedBrands.value : undefined,
        series: selectedSeries.value.length ? selectedSeries.value : undefined,
        stock: selectedStock.value || undefined,
        price_calc_mode: 'fixed',
      },
    })
    await pollExport(started.job_id)
  } catch (e) {
    exportError.value = getErrorMessage(e, 'Не удалось запустить экспорт')
    exporting.value = false
  }
}

function pollExport(jobId: string): Promise<void> {
  return new Promise(resolve => {
    let attempts = 0
    const tick = async () => {
      attempts++
      let job: ExportJobOut
      try {
        job = await request<ExportJobOut>(`/api/v1/catalog/export/${jobId}`)
      } catch (e) {
        exportError.value = getErrorMessage(e, 'Не удалось получить статус экспорта')
        exporting.value = false
        return resolve()
      }
      if (job.status === 'DONE' && job.url) {
        window.open(job.url, '_blank')
        exporting.value = false
        return resolve()
      }
      if (job.status === 'FAILED') {
        exportError.value = job.error || 'Экспорт не удался'
        exporting.value = false
        return resolve()
      }
      if (attempts >= EXPORT_MAX_POLLS) {
        exportError.value = 'Экспорт выполняется слишком долго, попробуйте позже'
        exporting.value = false
        return resolve()
      }
      exportTimer = setTimeout(tick, EXPORT_POLL_MS)
    }
    tick()
  })
}

onUnmounted(() => {
  if (exportTimer) clearTimeout(exportTimer)
})

// мини-помощники для карточки (в карточках каталога — thumb, §16 п.17)
const { thumbOf } = useProductPhoto()
function attrChips(p: ProductCard): { label: string; value: string }[] {
  const a = p.attributes || {}
  const out: { label: string; value: string }[] = []
  if (a.modules != null) out.push({ label: 'Модули', value: String(a.modules) })
  if (a.color) out.push({ label: 'Цвет', value: String(a.color) })
  if (a.ip_rating) out.push({ label: 'IP', value: String(a.ip_rating) })
  if (a.material) out.push({ label: 'Материал', value: String(a.material) })
  return out.slice(0, 4)
}
const stockLabel: Record<string, string> = { IN_STOCK: 'В наличии', PREORDER: 'Под заказ' }

onMounted(load)
</script>

<template>
  <div>
    <!-- Заголовок + тулбар -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Каталог</h1>
        <p class="text-sm text-ink-muted mt-1">
          <template v-if="!loading">Показано {{ products.length }} из {{ total }}</template>
          <template v-else>Загрузка…</template>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2 justify-end">
        <!-- Фильтры: на десктопе тоггл панели, на мобильном — открытие шторки -->
        <button class="btn-ghost py-2" @click="toggleFilters">
          <Icon name="heroicons:funnel" class="w-4 h-4" />
          Фильтры
        </button>
        <!-- Переключатель цены -->
        <div class="flex shrink-0 bg-surface border border-border rounded-pill p-1">
          <button
            class="px-3 py-1.5 rounded-pill text-sm font-medium whitespace-nowrap transition-colors shrink-0"
            :class="priceMode === 'discount' ? 'bg-primary text-white' : 'text-ink-muted'"
            @click="priceMode = 'discount'"
          >Со скидкой</button>
          <button
            class="px-3 py-1.5 rounded-pill text-sm font-medium whitespace-nowrap transition-colors shrink-0"
            :class="priceMode === 'retail' ? 'bg-primary text-white' : 'text-ink-muted'"
            @click="priceMode = 'retail'"
          >Розница</button>
        </div>
        <!-- Сортировка -->
        <BaseSelect v-model="sort" :options="sortOptions" class="min-w-[180px]" @change="applyFilters" />
        <!-- Экспорт каталога под текущие фильтры -->
        <div class="relative">
          <button
            class="btn-ghost py-2"
            :disabled="exporting"
            @click="exportMenuOpen = !exportMenuOpen"
          >
            <span
              v-if="exporting"
              class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-full animate-spin"
            />
            <Icon v-else name="heroicons:arrow-down-tray" class="w-4 h-4" />
            {{ exporting ? 'Готовим файл…' : 'Экспорт' }}
          </button>
          <div v-if="exportMenuOpen && !exporting" class="absolute right-0 mt-2 card p-1.5 w-44 z-20">
            <button
              class="w-full text-left px-3 py-2 rounded-card text-sm hover:bg-canvas transition-colors"
              @click="startExport('csv')"
            >
              CSV (Excel)
            </button>
            <button
              class="w-full text-left px-3 py-2 rounded-card text-sm hover:bg-canvas transition-colors"
              @click="startExport('xlsx')"
            >
              XLSX
            </button>
            <button
              class="w-full text-left px-3 py-2 rounded-card text-sm hover:bg-canvas transition-colors"
              @click="startExport('pdf')"
            >
              PDF
            </button>
          </div>
        </div>

        <!-- Переключатель вида -->
        <div class="flex shrink-0 bg-surface border border-border rounded-pill p-1">
          <button
            class="p-1.5 rounded-pill transition-colors"
            :class="viewMode === 'grid' ? 'bg-primary text-white' : 'text-ink-muted'"
            title="Плитка"
            @click="viewMode = 'grid'"
          >
            <Icon name="heroicons:squares-2x2" class="w-4 h-4" />
          </button>
          <button
            class="p-1.5 rounded-pill transition-colors"
            :class="viewMode === 'list' ? 'bg-primary text-white' : 'text-ink-muted'"
            title="Список"
            @click="viewMode = 'list'"
          >
            <Icon name="heroicons:list-bullet" class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="error" class="badge-danger w-full justify-center py-3 mb-6">{{ error }}</div>
    <div v-if="exportError" class="badge-warning w-full justify-center py-3 mb-6">{{ exportError }}</div>

    <div class="flex gap-6">
      <!-- Оверлей мобильной шторки фильтров -->
      <div
        v-if="drawerOpen"
        class="fixed inset-0 z-40 bg-ink/40 lg:hidden"
        @click="drawerOpen = false"
      />

      <!-- Фильтры: на десктопе — липкая колонка (тоггл кнопкой), на мобильном — шторка слева -->
      <aside
        class="w-72 lg:w-64 shrink-0 lg:sticky lg:top-[88px] lg:self-start"
        :class="[
          drawerOpen
            ? 'fixed inset-y-0 left-0 z-50 bg-canvas overflow-y-auto p-4'
            : 'hidden',
          desktopFiltersVisible ? 'lg:block' : 'lg:hidden',
        ]"
      >
        <div class="card p-5">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-semibold">Фильтры</h3>
            <button class="btn-ghost p-1.5 lg:hidden" aria-label="Закрыть фильтры" @click="drawerOpen = false">
              <Icon name="heroicons:x-mark" class="w-5 h-5" />
            </button>
          </div>

          <div class="mb-5">
            <label class="label">Поиск</label>
            <div class="relative">
              <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
              <input
                v-model="q"
                class="input pl-10"
                placeholder="Артикул, наименование"
                @keyup.enter="applyFilters"
              >
            </div>
          </div>

          <div v-if="filters.brands.length" class="mb-5">
            <label class="label">Производитель</label>
            <label v-for="b in visibleFilterItems(filters.brands, 'brands')" :key="b.id" class="flex items-center gap-2 text-sm py-1 cursor-pointer">
              <input v-model="selectedBrands" type="checkbox" :value="b.id" class="rounded border-border" @change="applyFilters" >
              {{ b.name }}
            </label>
            <button
              v-if="hiddenFilterCount(filters.brands, 'brands')"
              class="btn-ghost text-xs py-1 mt-1 text-primary"
              @click="expandedFilters.brands = true"
            >Показать все ({{ filters.brands.length }})</button>
            <button
              v-else-if="filters.brands.length > FILTER_COLLAPSED && expandedFilters.brands"
              class="btn-ghost text-xs py-1 mt-1 text-primary"
              @click="expandedFilters.brands = false"
            >Скрыть</button>
          </div>

          <div v-if="filters.series.length" class="mb-5">
            <label class="label">Серия</label>
            <label v-for="s in visibleFilterItems(filters.series, 'series')" :key="s.id" class="flex items-center gap-2 text-sm py-1 cursor-pointer">
              <input v-model="selectedSeries" type="checkbox" :value="s.id" class="rounded border-border" @change="applyFilters" >
              {{ s.name }}
            </label>
            <button
              v-if="hiddenFilterCount(filters.series, 'series')"
              class="btn-ghost text-xs py-1 mt-1 text-primary"
              @click="expandedFilters.series = true"
            >Показать все ({{ filters.series.length }})</button>
            <button
              v-else-if="filters.series.length > FILTER_COLLAPSED && expandedFilters.series"
              class="btn-ghost text-xs py-1 mt-1 text-primary"
              @click="expandedFilters.series = false"
            >Скрыть</button>
          </div>

          <div class="mb-5">
            <label class="label">Наличие</label>
            <BaseSelect v-model="selectedStock" :options="stockOptions" class="min-w-[150px]" @change="applyFilters" />
          </div>

          <button class="btn-ghost w-full justify-center" @click="resetFilters">Сбросить</button>
        </div>
      </aside>

      <!-- Сетка / Список -->
      <div class="flex-1 min-w-0">
        <!-- Skeletons -->
        <template v-if="loading">
          <div v-if="viewMode === 'grid'" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
            <div v-for="i in 6" :key="i" class="card p-5">
              <div class="skeleton aspect-square mb-4 rounded-card"/>
              <div class="skeleton h-4 w-1/3 mb-3"/>
              <div class="skeleton h-5 w-3/4 mb-2"/>
              <div class="skeleton h-4 w-1/2 mb-4"/>
              <div class="skeleton h-9 w-full"/>
            </div>
          </div>
          <div v-else class="card p-5">
            <div v-for="i in 8" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
          </div>
        </template>

        <!-- Пусто -->
        <div v-else-if="!products.length" class="card p-12 text-center text-ink-muted">
          <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
          <p>Ничего не найдено. Измените условия поиска или сбросьте фильтры.</p>
        </div>

        <!-- Плитка: на мобильном — горизонтальная карточка (фото слева, цена и
             корзина справа, всё помещается без скролла), на sm+ — вертикальная -->
        <div v-else-if="viewMode === 'grid'" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-5">
          <article v-for="p in products" :key="p.id" class="card card-hover p-3 sm:p-5 flex flex-row sm:flex-col gap-3 sm:gap-0">
            <!-- Фото: мобильный — компактный квадрат слева, десктоп — на всю ширину карточки -->
            <div class="relative w-28 h-28 sm:w-full sm:aspect-square shrink-0 bg-surface rounded-card sm:mb-4 flex items-center justify-center overflow-hidden">
              <img
                v-if="thumbOf(p.photo_key)"
                :src="thumbOf(p.photo_key)!"
                :alt="p.name"
                loading="lazy"
                class="w-full h-full object-contain"
              >
              <Icon v-else name="heroicons:photo" class="w-8 h-8 sm:w-10 sm:h-10 text-ink-faint" />
              <button
                class="absolute top-1.5 right-1.5 sm:top-2 sm:right-2 z-10 btn-ghost p-1 sm:p-1.5 rounded-full bg-surface/80 backdrop-blur"
                :class="favorites.isFav(p.sku) ? 'text-danger' : 'text-ink-muted'"
                :title="favorites.isFav(p.sku) ? 'Убрать из избранного' : 'В избранное'"
                @click="toggleFav(p.sku)"
              >
                <Icon
                  :name="favorites.isFav(p.sku) ? 'heroicons:heart-solid' : 'heroicons:heart'"
                  class="w-4 h-4 sm:w-5 sm:h-5"
                />
              </button>
            </div>

            <div class="flex-1 min-w-0 flex flex-col">
              <div class="flex items-start justify-between gap-2 mb-1">
                <span v-if="p.brand" class="badge-info">{{ p.brand.name }}</span>
                <span class="shrink-0 whitespace-nowrap" :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'">
                  {{ stockLabel[p.stock_status] || p.stock_status }}
                </span>
                <!-- Мало на складе: точный остаток известен и мал (0 < qty <= 5) -->
                <span v-if="p.stock_qty != null && p.stock_qty > 0 && p.stock_qty <= 5" class="badge-warning whitespace-nowrap">
                  Осталось {{ p.stock_qty }} шт
                </span>
              </div>
              <NuxtLink :to="`/catalog/${p.sku}`" class="block font-semibold text-sm sm:text-base mb-1 line-clamp-2 hover:text-primary transition-colors">
                {{ p.name }}
              </NuxtLink>
              <p class="text-xs text-ink-faint mb-2 sm:mb-3">Артикул: {{ p.sku }}<span v-if="p.series"> · {{ p.series.name }}</span></p>

              <!-- Характеристики: стабильная сетка 2 колонки, фиксированный порядок полей -->
              <div v-if="attrChips(p).length" class="hidden sm:grid grid-cols-2 gap-x-4 gap-y-1 mb-3">
                <div v-for="c in attrChips(p)" :key="c.label" class="flex items-baseline gap-1 text-xs min-w-0">
                  <span class="text-ink-faint shrink-0">{{ c.label }}:</span>
                  <span class="font-medium truncate">{{ c.value }}</span>
                </div>
              </div>

              <div class="mt-auto">
                <div v-if="priceMode === 'discount' && p.has_discount" class="flex items-baseline gap-2 mb-2 sm:mb-3">
                  <span class="text-lg sm:text-xl font-bold text-primary">{{ formatMoney(p.client_price, p.currency) }}</span>
                  <span class="text-xs sm:text-sm text-ink-faint line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
                </div>
                <div v-else class="mb-2 sm:mb-3">
                  <span class="text-lg sm:text-xl font-bold">{{ formatMoney(p.retail_price, p.currency) }}</span>
                </div>
                <div class="flex items-stretch gap-2">
                  <input
                    type="number"
                    min="1"
                    :value="getQty(p.sku)"
                    class="input py-2 w-14 sm:w-20 text-center shrink-0"
                    @input="setQty(p.sku, +($event.target as HTMLInputElement).value)"
                  >
                  <button
                    class="btn-primary flex-1 min-w-0 whitespace-nowrap px-2 sm:px-4 py-2 text-xs sm:text-sm"
                    :disabled="addingSku === p.sku"
                    @click="addToCart(p)"
                  >
                    <span v-if="addingSku === p.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                    <Icon v-else-if="addedSku === p.sku" name="heroicons:check" class="w-4 h-4" />
                    <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                    <span class="hidden min-[400px]:inline">{{ addedSku === p.sku ? 'Добавлено' : 'В корзину' }}</span>
                  </button>
                </div>
              </div>
            </div>
          </article>
        </div>

        <!-- Список -->
        <div v-else class="card overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full text-sm table-fixed">
              <thead>
                <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
                  <th class="px-2 py-2 font-medium w-[11%]">Артикул</th>
                  <th class="px-2 py-2 font-medium w-[30%]">Наименование</th>
                  <th class="px-2 py-2 font-medium w-[11%] hidden sm:table-cell">Бренд</th>
                  <th class="px-2 py-2 font-medium w-[10%] hidden sm:table-cell">Серия</th>
                  <th class="px-2 py-2 font-medium w-[10%] hidden sm:table-cell">Наличие</th>
                  <th class="px-2 py-2 font-medium text-right w-[16%] sm:w-[11%]">Цена</th>
                  <th class="px-2 py-2 font-medium text-center w-[18%] sm:w-[9%] whitespace-nowrap">Кол-во</th>
                  <th class="px-2 py-2 font-medium text-right w-[12%] sm:w-[5%]" />
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in products" :key="p.id" class="border-t border-border hover:bg-canvas/60">
                  <td class="px-2 py-2 font-mono text-xs max-w-0 truncate" :title="p.sku">{{ p.sku }}</td>
                  <td class="px-2 py-2 truncate" :title="p.name">
                    <NuxtLink :to="`/catalog/${p.sku}`" class="font-medium hover:text-primary transition-colors">
                      {{ p.name }}
                    </NuxtLink>
                  </td>
                  <td class="px-2 py-2 text-ink-muted whitespace-nowrap truncate hidden sm:table-cell">{{ p.brand?.name || '—' }}</td>
                  <td class="px-2 py-2 text-ink-muted whitespace-nowrap truncate hidden sm:table-cell">{{ p.series?.name || '—' }}</td>
                  <td class="px-2 py-2 hidden sm:table-cell">
                    <span class="badge whitespace-nowrap" :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'">
                      {{ stockLabel[p.stock_status] || p.stock_status }}
                    </span>
                    <span v-if="p.stock_qty != null && p.stock_qty > 0 && p.stock_qty <= 5" class="badge-warning block w-fit mt-1">
                      Осталось {{ p.stock_qty }} шт
                    </span>
                  </td>
                  <td class="px-2 py-2 text-right whitespace-nowrap">
                    <template v-if="priceMode === 'discount' && p.has_discount">
                      <span class="font-bold text-primary">{{ formatMoney(p.client_price, p.currency) }}</span>
                      <span class="block text-xs text-ink-faint line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
                    </template>
                    <span v-else class="font-bold">{{ formatMoney(p.retail_price, p.currency) }}</span>
                  </td>
                  <td class="px-2 py-2 text-center">
                    <input
                      type="number"
                      min="1"
                      :value="getQty(p.sku)"
                      class="input py-1.5 w-12 sm:w-14 text-center"
                      @input="setQty(p.sku, +($event.target as HTMLInputElement).value)"
                    >
                  </td>
                  <td class="px-2 py-2 text-right">
                    <button
                      class="btn-primary p-1.5"
                      :disabled="addingSku === p.sku"
                      @click="addToCart(p)"
                    >
                      <span v-if="addingSku === p.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                      <Icon v-else-if="addedSku === p.sku" name="heroicons:check" class="w-4 h-4" />
                      <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Пагинация -->
        <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-8">
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
    </div>
  </div>
</template>
