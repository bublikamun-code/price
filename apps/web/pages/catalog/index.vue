<script setup lang="ts">
// Каталог / Прайс-лист — ключевая страница (SITEMAP.md §6).
// Реальные данные: GET /api/v1/catalog/products, /catalog/filters.
// Экспорт каталога под текущие фильтры: POST /catalog/export + опрос статуса.
import type { CatalogPage, ExportFormat, ExportJobOut, ExportStartOut, FiltersOut, ProductCard } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Каталог' })

const { request } = useApi()
const route = useRoute()
const router = useRouter()

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
// 12 = 4 ряда плитки; пагинация прилипает к низу экрана, её видно всегда
const PER_PAGE = 12

const sortOptions = [
  { value: 'name', label: 'Название А→Я' },
  { value: '-name', label: 'Название Я→А' },
  { value: 'price', label: 'Цена ↑' },
  { value: '-price', label: 'Цена ↓' },
  { value: 'sku', label: 'Артикул' },
]
const modelOptions = computed(() => [
  { value: '', label: 'Все модели' },
  ...(filters.value.models ?? []).map((m) => ({ value: m, label: m })),
])

const loading = ref(true)
const error = ref('')
const products = ref<ProductCard[]>([])
const total = ref(0)
const filters = ref<FiltersOut>({ brands: [], series: [], stock: [], models: [] })

// Корзина: добавление товара прямо из карточки.
// Синк с корзиной: товар, уже лежащий в ней, показывает своё количество,
// изменение кол-ва в карточке меняет его и в корзине (и наоборот).
const cart = useCart()
const qtyMap = reactive<Record<string, number>>({})
const addingSku = ref<string | null>(null)
const addedSku = ref<string | null>(null)
function inCartQty(sku: string): number {
  return cart.cart.value?.items.find(i => i.sku === sku)?.quantity ?? 0
}
function getQty(sku: string): number {
  const inCart = inCartQty(sku)
  return inCart > 0 ? inCart : qtyMap[sku] ?? 1
}
function setQty(sku: string, v: number) {
  const qty = Math.max(1, Math.floor(v) || 1)
  if (inCartQty(sku) > 0) {
    // Уже в корзине — меняем количество там (страница /cart и значок в шапке
    // читают тот же module-level ref, обновятся сами).
    cart.update(sku, { quantity: qty }).catch((e) => {
      error.value = getErrorMessage(e, 'Не удалось изменить количество')
    })
  } else {
    qtyMap[sku] = qty
  }
}
async function addToCart(p: ProductCard) {
  if (addingSku.value) return
  addingSku.value = p.sku
  try {
    if (inCartQty(p.sku) > 0) {
      // POST /cart/items на бэкенде инкрементирует кол-во, поэтому для товара
      // в корзине ставим целевое значение через PUT, а не добавляем поверх.
      await cart.update(p.sku, { quantity: getQty(p.sku) })
      cart.lastAdded.value = cart.cart.value?.items.find(i => i.sku === p.sku) ?? null
    } else {
      await cart.add({ sku: p.sku, quantity: getQty(p.sku) })
    }
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
  // значения могут быть "id1,id2" (наша запись URL) или массивом (повторы в query)
  const raw = Array.isArray(v) ? v : [String(v)]
  return raw.flatMap((x) => String(x).split(',')).filter(Boolean)
}
selectedBrands.value = idsFromQuery('brand')
selectedSeries.value = idsFromQuery('series')
const selectedStock = ref<string>('') // '' | IN_STOCK | PREORDER
const selectedModel = ref<string>('') // Щит распределительный / Щит мультимедиа / Аксессуары
selectedModel.value = (route.query.model as string) || ''
const sort = ref<Sort>('name')
// Восстановление состояния из URL при F5 (аудит UX 19.09)
const qSort = route.query.sort as string
if (qSort && ['name', '-name', 'price', '-price', 'sku'].includes(qSort)) sort.value = qSort as Sort
const qStock = route.query.stock as string
if (qStock === 'IN_STOCK' || qStock === 'PREORDER') selectedStock.value = qStock
const page = ref(1)
const viewMode = ref<'grid' | 'list'>('grid')

// Сворачиваемые группы фильтров (паттерн для новых фильтров: добавь ключ +
// оберни секцию как Производитель/Серия — кнопка-заголовок со счётчиком)
const collapsedGroups = reactive({ brands: false, series: false, stock: false, models: false })
function toggleGroup(key: keyof typeof collapsedGroups) {
  collapsedGroups[key] = !collapsedGroups[key]
}
// Пилот shadcn-vue Select (reka-ui) откачен: popper-портал моргал и сдвигал
// контент при открытии. Селекты — усиленный BaseSelect (рендер в потоке).

// Видимость панели фильтров:
// - десктоп (lg+): панель всегда показана (кнопки скрытия нет)
// - мобильный (<lg): aside открыт только как шторка (drawerOpen), по умолчанию закрыт
const drawerOpen = ref(false)
function toggleFilters() {
  drawerOpen.value = true
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

// Seq-guard против гонок: медленный ответ с устаревшими фильтрами не должен
// перетирать результат свежего запроса (P2 §3.3).
let loadSeq = 0
// Первая загрузка — скелетоны; повторные (фильтры/сортировка/пагинация) —
// старый список с затемнением, без моргания и прыжков высоты (аудит UX 19.09)
const firstLoadDone = ref(false)

async function load() {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  // URL отражает текущие фильтры: после F5 не «возвращаются» снятые галочки
  const urlQuery: Record<string, string> = {}
  if (q.value) urlQuery.q = q.value
  if (selectedBrands.value.length) urlQuery.brand = selectedBrands.value.join(',')
  if (selectedSeries.value.length) urlQuery.series = selectedSeries.value.join(',')
  if (selectedStock.value) urlQuery.stock = selectedStock.value
  if (selectedModel.value) urlQuery.model = selectedModel.value
  if (sort.value !== 'name') urlQuery.sort = sort.value
  if (page.value > 1) urlQuery.page = String(page.value)
  void router.replace({ query: urlQuery }).catch(() => {})
  try {
    const [catalog, f] = await Promise.all([
      request<CatalogPage>('/api/v1/catalog/products', {
        query: {
          q: q.value || undefined,
          brand: selectedBrands.value.length ? selectedBrands.value : undefined,
          series: selectedSeries.value.length ? selectedSeries.value : undefined,
          stock: selectedStock.value || undefined,
          model: selectedModel.value || undefined,
          sort: sort.value,
          page: page.value,
          per_page: PER_PAGE,
        },
      }),
      request<FiltersOut>('/api/v1/catalog/filters'),
    ])
    if (seq !== loadSeq) return // устаревший ответ — игнорируем
    products.value = catalog.data
    total.value = catalog.meta.total
    filters.value = f
  } catch (e) {
    if (seq !== loadSeq) return
    error.value = getErrorMessage(e, 'Не удалось загрузить каталог')
  } finally {
    if (seq === loadSeq) {
      loading.value = false
      firstLoadDone.value = true
    }
  }
}

// Debounced поиск: срабатывает через 300мс после последнего ввода
let searchTimer: ReturnType<typeof setTimeout>
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    applyFilters()
  }, 300)
}

// Массовое добавление в корзину из табличного вида
const selectedSkus = ref<Set<string>>(new Set())
const bulkAdding = ref(false)
const selectAll = computed({
  get: () => products.value.length > 0 && products.value.every(p => selectedSkus.value.has(p.sku)),
  set: (v: boolean) => {
    if (v) {
      products.value.forEach(p => selectedSkus.value.add(p.sku))
    } else {
      products.value.forEach(p => selectedSkus.value.delete(p.sku))
    }
    selectedSkus.value = new Set(selectedSkus.value)
  },
})
function toggleSku(sku: string) {
  const s = new Set(selectedSkus.value)
  if (s.has(sku)) s.delete(sku)
  else s.add(sku)
  selectedSkus.value = s
}
async function bulkAddToCart() {
  if (bulkAdding.value || !selectedSkus.value.size) return
  bulkAdding.value = true
  error.value = ''
  try {
    for (const sku of selectedSkus.value) {
      await cart.add({ sku, quantity: getQty(sku) })
    }
    selectedSkus.value = new Set()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось добавить выбранные товары')
  } finally {
    bulkAdding.value = false
  }
}

function applyFilters() {
  page.value = 1
  selectedSkus.value = new Set()
  load()
}
function resetFilters() {
  q.value = ''
  selectedBrands.value = []
  selectedSeries.value = []
  selectedStock.value = ''
  selectedModel.value = ''
  sort.value = 'name'
  page.value = 1
  selectedSkus.value = new Set()
  load()
}
function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  selectedSkus.value = new Set()
  load()
}

// Окно пагинации (1 ... 4 5 6 ... 20)
function paginationWindow(total: number, current: number, window = 2): (number | '...')[] {
  const pages: (number | '...')[] = []
  const start = Math.max(2, current - window)
  const end = Math.min(total - 1, current + window)
  pages.push(1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  if (total > 1) pages.push(total)
  return pages
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
        model: selectedModel.value || undefined,
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
  clearTimeout(searchTimer)
})

// мини-помощники для карточки (в карточках каталога — thumb, §16 п.17)
const { thumbOf } = useProductPhoto()
function attrChips(p: ProductCard): { label: string; value: string }[] {
  const a = p.attributes || {}
  const out: { label: string; value: string }[] = []
  if (a.model) out.push({ label: 'Модель', value: String(a.model) })
  if (a.modules != null) out.push({ label: 'Модули', value: String(a.modules) })
  if (a.color) out.push({ label: 'Цвет', value: String(a.color) })
  if (a.ip_rating) out.push({ label: 'IP', value: String(a.ip_rating) })
  if (a.material) out.push({ label: 'Материал', value: String(a.material) })
  return out.slice(0, 4)
}
const stockLabel: Record<string, string> = { IN_STOCK: 'В наличии', PREORDER: 'Под заказ', ARCHIVED: 'Снят с производства' }
// Фильтры «Наличие»/«Модель»: чекбоксы в стиле Производитель/Серия.
// Бэкенд принимает одиночное значение — чекбокс работает как переключатель:
// клик по выбранному снимает фильтр (= «Любое»/«Все модели»).
const stockCheckOptions = [
  { value: 'IN_STOCK', label: 'В наличии' },
  { value: 'PREORDER', label: 'Под заказ' },
]
function toggleStock(v: string) {
  selectedStock.value = selectedStock.value === v ? '' : v
  applyFilters()
}
function toggleModel(m: string) {
  selectedModel.value = selectedModel.value === m ? '' : m
  applyFilters()
}
// Табличный вид: статус — иконка + тултип (классы — те же, что у бейджей наличия).
const STOCK_ICON: Record<string, { icon: string; cls: string }> = {
  IN_STOCK: { icon: 'heroicons:check-circle-20-solid', cls: 'text-success' },
  PREORDER: { icon: 'heroicons:clock', cls: 'text-warning' },
  ARCHIVED: { icon: 'heroicons:archive-box-x-mark', cls: 'text-danger' },
}

onMounted(load)
</script>

<template>
  <div>
    <!-- Заголовок + тулбар: подняты к верхней границе меню (sidebar).
         Мобайл: заголовок делит строку с фильтрами и видом (2 ряда вместо 3),
         экспорт — иконка; на sm+ обёртки растворяются в колонку справа. -->
    <div class="flex flex-wrap items-center justify-between gap-2 -mt-2 lg:-mt-4 mb-3 sm:mb-5 sm:gap-4">
        <div class="flex-1 min-w-0 flex items-baseline gap-2 sm:block">
          <h1 class="text-xl sm:text-2xl font-bold">Каталог</h1>
          <p class="text-xs sm:text-sm text-ink-muted sm:mt-1">
            <!-- при повторных загрузках держим прежний текст: никакой мигалки -->
            {{ products.length }} из {{ total }}
          </p>
        </div>
        <div class="contents sm:flex sm:flex-row sm:flex-wrap sm:items-center sm:justify-end sm:gap-2">
          <!-- Мобильный ряд 1 — рядом с заголовком: фильтры | вид
               (на десктопе обёртки растворяются) -->
          <div class="flex items-center gap-1.5 shrink-0 sm:contents">
            <!-- Фильтры: кнопка только на мобильном (иконка) и планшете (с текстом);
                на десктопе панель всегда видна -->
            <button class="btn-ghost py-1.5 px-2 sm:px-3 lg:hidden" title="Фильтры" @click="toggleFilters">
              <Icon name="heroicons:funnel" class="w-4 h-4" />
              <span class="hidden sm:inline">Фильтры</span>
            </button>
            <!-- Переключатель вида -->
            <div class="flex shrink-0 bg-surface border border-border rounded-pill p-0.5 sm:p-1">
              <button
                class="p-1 sm:p-1.5 rounded-pill transition-colors"
                :class="viewMode === 'grid' ? 'bg-primary text-white' : 'text-ink-muted'"
                title="Плитка"
                @click="viewMode = 'grid'"
              >
                <Icon name="heroicons:squares-2x2" class="w-4 h-4" />
              </button>
              <button
                class="p-1 sm:p-1.5 rounded-pill transition-colors"
                :class="viewMode === 'list' ? 'bg-primary text-white' : 'text-ink-muted'"
                title="Список"
                @click="viewMode = 'list'"
              >
                <Icon name="heroicons:list-bullet" class="w-4 h-4" />
              </button>
            </div>
          </div>
          <!-- Мобильный ряд 2 — своя строка (basis-full); на десктопе остаётся
               единым блоком: сортировка | экспорт в одной линии без пустот -->
          <div class="flex items-center gap-2 basis-full sm:basis-auto sm:gap-3">
            <!-- Сортировка: BaseSelect — рендер в потоке без портала/popper
                 (reka-портал давал моргание и сдвиг, аудит UX 19.09) -->
            <BaseSelect v-model="sort" :options="sortOptions" class="flex-1 sm:flex-none sm:min-w-[180px]" @change="applyFilters" />
            <!-- Экспорт каталога под текущие фильтры (на узких — иконка) -->
            <div class="relative shrink-0">
              <button
                class="btn-ghost py-1.5 sm:py-2"
                :disabled="exporting"
                @click="exportMenuOpen = !exportMenuOpen"
              >
                <span
                  v-if="exporting"
                  class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-full animate-spin"
                />
                <Icon v-else name="heroicons:arrow-down-tray" class="w-4 h-4" />
                <span class="hidden min-[400px]:inline">{{ exporting ? 'Готовим файл…' : 'Экспорт' }}</span>
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

      <!-- Фильтры: в табличном виде — на всю высоту таблицы (Сбросить внизу),
          в плиточном — компактная колонка по высоте содержимого; на мобильном
          — шторка слева -->
      <aside
        class="w-72 lg:w-64 shrink-0"
        :class="[
          drawerOpen
            ? 'fixed inset-y-0 left-0 z-50 bg-canvas overflow-y-auto scrollbar-none p-3'
            : 'hidden',
          'lg:block',
          viewMode === 'grid' ? 'lg:self-start' : '',
        ]"
      >
        <!-- card — только для статичной панели на lg; в мобильной шторке
             белая подложка не нужна: фильтры лежат прямо на фоне шторки -->
        <div class="p-3 sm:p-4" :class="[drawerOpen ? '' : 'card', viewMode === 'list' ? 'h-full flex flex-col' : '']">
          <div class="flex items-center justify-between mb-2 sm:mb-4">
            <h3 class="font-semibold">Фильтры</h3>
            <button class="btn-ghost p-1.5 lg:hidden" aria-label="Закрыть фильтры" @click="drawerOpen = false">
              <Icon name="heroicons:x-mark" class="w-5 h-5" />
            </button>
          </div>

          <div class="mb-3 sm:mb-4">
            <div class="relative">
              <Icon name="heroicons:magnifying-glass" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
              <input
                v-model="q"
                class="input pl-9 pr-9 py-2 text-sm"
                placeholder="Артикул, наименование…"
                @input="onSearchInput"
                @keyup.enter="applyFilters"
              >
              <!-- тихий индикатор поиска: без смены контента и прыжков -->
              <span
                v-if="loading"
                class="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"
                aria-hidden="true"
              />
            </div>
          </div>

          <div v-if="filters.brands.length" class="mb-3 sm:mb-4">
            <button
              class="label w-full flex items-center justify-between cursor-pointer"
              :aria-expanded="!collapsedGroups.brands"
              @click="toggleGroup('brands')"
            >
              <span>Производитель<template v-if="selectedBrands.length"> · <span class="text-primary font-semibold">{{ selectedBrands.length }}</span></template></span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint transition-transform" :class="collapsedGroups.brands ? '-rotate-90' : ''" />
            </button>
            <div v-show="!collapsedGroups.brands" class="mt-1">
              <label v-for="b in visibleFilterItems(filters.brands, 'brands')" :key="b.id" class="flex items-center gap-2 text-sm py-0.5 sm:py-1 cursor-pointer">
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
          </div>

          <div v-if="filters.series.length" class="mb-3 sm:mb-4">
            <button
              class="label w-full flex items-center justify-between cursor-pointer"
              :aria-expanded="!collapsedGroups.series"
              @click="toggleGroup('series')"
            >
              <span>Серия<template v-if="selectedSeries.length"> · <span class="text-primary font-semibold">{{ selectedSeries.length }}</span></template></span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint transition-transform" :class="collapsedGroups.series ? '-rotate-90' : ''" />
            </button>
            <div v-show="!collapsedGroups.series" class="mt-1">
              <label v-for="s in visibleFilterItems(filters.series, 'series')" :key="s.id" class="flex items-center gap-2 text-sm py-0.5 sm:py-1 cursor-pointer">
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
          </div>

          <div class="mb-3 sm:mb-4">
            <button
              class="label w-full flex items-center justify-between cursor-pointer"
              :aria-expanded="!collapsedGroups.stock"
              @click="toggleGroup('stock')"
            >
              <span>Наличие<template v-if="selectedStock"> · <span class="text-primary font-semibold">{{ stockLabel[selectedStock] }}</span></template></span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint transition-transform" :class="collapsedGroups.stock ? '-rotate-90' : ''" />
            </button>
            <div v-show="!collapsedGroups.stock" class="mt-1">
              <label v-for="o in stockCheckOptions" :key="o.value" class="flex items-center gap-2 text-sm py-0.5 sm:py-1 cursor-pointer">
                <input type="checkbox" :checked="selectedStock === o.value" class="rounded border-border" @change="toggleStock(o.value)">
                {{ o.label }}
              </label>
            </div>
          </div>

          <div class="mb-3 sm:mb-4">
            <button
              class="label w-full flex items-center justify-between cursor-pointer"
              :aria-expanded="!collapsedGroups.models"
              @click="toggleGroup('models')"
            >
              <span>Модель<template v-if="selectedModel"> · <span class="text-primary font-semibold">1</span></template></span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint transition-transform" :class="collapsedGroups.models ? '-rotate-90' : ''" />
            </button>
            <div v-show="!collapsedGroups.models" class="mt-1">
              <label v-for="o in modelOptions" :key="o.value || 'all'" class="flex items-center gap-2 text-sm py-0.5 sm:py-1 cursor-pointer">
                <input type="checkbox" :checked="selectedModel === o.value" class="rounded border-border" @change="toggleModel(String(o.value))">
                {{ o.value ? o.label : 'Все модели' }}
              </label>
            </div>
          </div>

          <button
            class="btn-ghost w-full justify-center"
            :class="viewMode === 'list' ? 'mt-auto' : ''"
            @click="resetFilters"
          >Сбросить</button>
        </div>
      </aside>

      <!-- Сетка / Список -->
      <div class="flex-1 min-w-0">
        <!-- Skeletons: только при первой загрузке; повторные — старый список с затемнением -->
        <template v-if="loading && !firstLoadDone">
          <div v-if="viewMode === 'grid'" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
            <div v-for="i in 6" :key="i" class="card p-5">
              <div class="skeleton h-28 sm:h-52 mb-4 rounded-card"/>
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
        <div v-else-if="!products.length" class="card p-8 sm:p-12 text-center text-ink-muted">
          <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
          <p>Ничего не найдено. Измените условия поиска или сбросьте фильтры.</p>
        </div>

        <!-- Плитка: на мобильном — горизонтальная карточка (фото слева, цена и
             корзина справа, всё помещается без скролла), на sm+ — вертикальная -->
        <div v-else-if="viewMode === 'grid'" key="grid" class="ui-fade-in grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5 sm:gap-5" :class="loading ? 'pointer-events-none' : ''">
          <article v-for="p in products" :key="p.id" class="card card-hover p-2.5 sm:p-5 flex flex-row sm:flex-col gap-2.5 sm:gap-0">
            <!-- Фото: мобильный — компактный квадрат слева, десктоп — на всю
                 ширину карточки, единая высота у всех (object-contain) -->
            <div class="relative w-24 h-24 sm:w-full sm:h-52 shrink-0 bg-surface rounded-card sm:mb-4 flex items-center justify-center overflow-hidden">
              <img
                v-if="thumbOf(p.photo_key)"
                :src="thumbOf(p.photo_key)!"
                :alt="p.name"
                loading="lazy"
                class="img-fade w-full h-full object-contain"
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
              <div class="flex flex-wrap items-center gap-2 mb-1">
                <span v-if="p.brand" class="badge-info">{{ p.brand.name }}</span>
                <span class="shrink-0 whitespace-nowrap" :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'">
                  {{ stockLabel[p.stock_status] || p.stock_status }}
                </span>
                <!-- Мало на складе: точный остаток известен и мал (0 < qty <= 5) -->
                <span v-if="p.stock_qty != null && p.stock_qty > 0 && p.stock_qty <= 5" class="badge-warning whitespace-nowrap">
                  Осталось {{ p.stock_qty }} шт
                </span>
              </div>
              <NuxtLink :to="`/catalog/${p.sku}`" class="block font-semibold text-sm sm:text-base mb-0.5 sm:mb-1 line-clamp-1 sm:line-clamp-2 hover:text-primary transition-colors">
                {{ p.name }}
              </NuxtLink>
              <p class="text-xs text-ink-faint mb-1.5 sm:mb-3 truncate">Артикул: {{ p.sku }}<span v-if="p.series"> · {{ p.series.name }}</span></p>

              <!-- Характеристики: стабильная сетка 2 колонки, фиксированный порядок полей -->
              <div v-if="attrChips(p).length" class="hidden sm:grid grid-cols-2 gap-x-4 gap-y-1 mb-3">
                <div v-for="c in attrChips(p)" :key="c.label" class="flex items-baseline gap-1 text-xs min-w-0">
                  <span class="text-ink-faint shrink-0">{{ c.label }}:</span>
                  <span class="font-medium truncate">{{ c.value }}</span>
                </div>
              </div>

              <div class="mt-auto">
                <!-- Товар без прайса: не показываем «0,00» (§8 — цены только из активного импорта) -->
                <div v-if="!(Number(p.client_price) > 0)" class="mb-1.5 sm:mb-3">
                  <span class="text-sm text-ink-muted">Цена по запросу</span>
                </div>
                <div v-else-if="p.has_discount" class="flex items-baseline gap-2 mb-1.5 sm:mb-3">
                  <span class="text-base sm:text-xl font-bold text-primary">{{ formatMoney(p.client_price, p.currency) }}</span>
                  <span class="text-xs sm:text-sm text-ink-faint line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
                </div>
                <div v-else class="mb-1.5 sm:mb-3">
                  <span class="text-base sm:text-xl font-bold">{{ formatMoney(p.client_price, p.currency) }}</span>
                </div>
                <div class="flex items-stretch gap-2">
                  <input
                    type="number"
                    min="1"
                    :value="getQty(p.sku)"
                    class="input py-1.5 sm:py-2 w-12 sm:w-20 text-center shrink-0"
                    @input="setQty(p.sku, +($event.target as HTMLInputElement).value)"
                  >
                  <button
                    class="btn-primary flex-1 min-w-0 whitespace-nowrap px-2 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm"
                    :class="addedSku !== p.sku && inCartQty(p.sku) > 0 ? '!bg-success' : ''"
                    :disabled="addingSku === p.sku"
                    :title="inCartQty(p.sku) > 0 ? `В корзине: ${inCartQty(p.sku)} шт` : 'В корзину'"
                    @click="addToCart(p)"
                  >
                    <span v-if="addingSku === p.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                    <Icon v-else-if="addedSku === p.sku || inCartQty(p.sku) > 0" name="heroicons:check" class="w-4 h-4" />
                    <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                    <span class="hidden min-[400px]:inline">{{ addedSku === p.sku ? 'Добавлено' : (inCartQty(p.sku) > 0 ? `В корзине · ${inCartQty(p.sku)}` : 'В корзину') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </article>
        </div>

        <!-- Список -->
        <div v-else key="list" class="ui-fade-in card overflow-hidden" :class="loading ? 'pointer-events-none' : ''">
          <div class="overflow-x-auto">
            <table class="w-full text-sm table-fixed">
              <thead>
                <tr class="text-ink-muted text-left bg-surface-2 border-b border-border text-[11px] sm:text-xs">
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium w-[5%] sm:w-[4%] text-center">
                    <input
                      type="checkbox"
                      :checked="selectAll"
                      class="rounded border-border"
                      @change="selectAll = ($event.target as HTMLInputElement).checked"
                    >
                  </th>
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium w-[13%] sm:w-[11%] truncate">Арт.</th>
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium w-[28%] sm:w-[32%] truncate">Наименование</th>
                  <th class="px-2 py-1.5 sm:py-2 font-medium w-[10%] hidden sm:table-cell">Наличие</th>
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium text-right w-[20%] sm:w-[14%]">Цена</th>
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium text-center w-[18%] sm:w-[19%] whitespace-nowrap">Кол-во</th>
                  <th class="px-1 sm:px-2 py-1.5 sm:py-2 font-medium text-right w-[16%] sm:w-[8%]" />
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in products" :key="p.id" class="border-t border-border hover:bg-canvas/60 transition-colors duration-150" :class="{ 'bg-primary/5': selectedSkus.has(p.sku) }">
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 text-center">
                    <input
                      type="checkbox"
                      :checked="selectedSkus.has(p.sku)"
                      class="rounded border-border"
                      @change="toggleSku(p.sku)"
                    >
                  </td>
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 font-mono text-[11px] sm:text-xs max-w-0 truncate" :title="p.sku">{{ p.sku }}</td>
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 max-w-0 truncate" :title="p.name">
                    <NuxtLink :to="`/catalog/${p.sku}`" class="font-medium hover:text-primary transition-colors">
                      {{ p.name }}
                    </NuxtLink>
                  </td>
                  <td class="px-2 py-1.5 sm:py-2 hidden sm:table-cell">
                    <!-- Только SVG-значок наличия; расшифровка — в hover-тултипе -->
                    <span class="relative inline-flex group">
                      <Icon
                        :name="STOCK_ICON[p.stock_status]?.icon || 'heroicons:question-mark-circle'"
                        class="w-5 h-5"
                        :class="STOCK_ICON[p.stock_status]?.cls || 'text-ink-faint'"
                      />
                      <span class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-xs rounded-card bg-surface text-ink border border-border shadow-lg whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity z-10">
                        {{ stockLabel[p.stock_status] || p.stock_status }}
                      </span>
                    </span>
                    <span v-if="p.stock_qty != null && p.stock_qty > 0 && p.stock_qty <= 5" class="badge-warning block w-fit mt-1">
                      Осталось {{ p.stock_qty }} шт
                    </span>
                  </td>
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 text-right max-w-0">
                    <!-- Товар без прайса: «по запросу» вместо 0,00 (§8) -->
                    <span v-if="!(Number(p.client_price) > 0)" class="text-xs sm:text-sm text-ink-muted block truncate">По запросу</span>
                    <template v-else-if="p.has_discount">
                      <!-- На мобильном валюта и старая цена скрыты, чтобы сумма не налезала на соседние колонки -->
                      <span class="font-bold text-primary block truncate text-xs sm:text-sm">{{ formatMoney(p.client_price) }}<span class="hidden sm:inline"> {{ p.currency }}</span></span>
                      <span class="hidden sm:block text-xs text-ink-faint line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
                    </template>
                    <span v-else class="font-bold block truncate text-xs sm:text-sm">{{ formatMoney(p.client_price) }}<span class="hidden sm:inline"> {{ p.currency }}</span></span>
                  </td>
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 text-center">
                    <input
                      type="number"
                      min="1"
                      :value="getQty(p.sku)"
                      class="input py-1.5 w-12 sm:w-14 text-center"
                      @input="setQty(p.sku, +($event.target as HTMLInputElement).value)"
                    >
                  </td>
                  <td class="px-1 sm:px-2 py-1.5 sm:py-2 text-right">
                    <button
                      class="btn-primary p-1 sm:p-1.5"
                      :class="addedSku !== p.sku && inCartQty(p.sku) > 0 ? '!bg-success' : ''"
                      :disabled="addingSku === p.sku"
                      :title="inCartQty(p.sku) > 0 ? `В корзине: ${inCartQty(p.sku)} шт — кол-во меняется в соседнем поле` : 'В корзину'"
                      @click="addToCart(p)"
                    >
                      <span v-if="addingSku === p.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                      <Icon v-else-if="addedSku === p.sku || inCartQty(p.sku) > 0" name="heroicons:check" class="w-4 h-4" />
                      <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Floating bulk-add bar (list view only) -->
        <div
          v-if="selectedSkus.size > 0 && viewMode === 'list'"
          class="fixed bottom-4 left-1/2 -translate-x-1/2 z-30 card shadow-xl flex items-center gap-4 px-5 py-3"
        >
          <span class="text-sm font-medium whitespace-nowrap">
            Выбрано: {{ selectedSkus.size }} {{ pluralize(selectedSkus.size, 'товар', 'товара', 'товаров') }}
          </span>
          <button
            class="btn-primary px-5 py-2 text-sm whitespace-nowrap"
            :disabled="bulkAdding"
            @click="bulkAddToCart"
          >
            <span v-if="bulkAdding" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
            Добавить в корзину
          </button>
          <button
            class="btn-ghost p-1.5 text-ink-faint hover:text-danger"
            title="Снять выделение"
            @click="selectedSkus = new Set()"
          >
            <Icon name="heroicons:x-mark" class="w-4 h-4" />
          </button>
        </div>

        <!-- Пагинация: на десктопе прилипает к низу экрана — кнопки страниц
            видны всегда, строк таблицы/карточек помещается сколько влезает;
            на мобильном — обычный поток под списком (инаже перекрыла бы
            нижнюю навигацию) -->
        <div
          v-if="totalPages > 1"
          class="mt-4 py-1.5 card rounded-card backdrop-blur-[20px] lg:sticky lg:bottom-3 lg:z-10 transition-opacity duration-200"
          :class="loading ? 'opacity-40 pointer-events-none' : 'opacity-100'"
        >
          <nav class="flex items-center justify-center gap-1">
            <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
              <Icon name="heroicons:chevron-left" class="w-5 h-5" />
            </button>
            <template v-for="(pgn, idx) in paginationWindow(totalPages, page)" :key="idx">
              <span v-if="pgn === '...'" class="px-2 text-ink-faint">…</span>
              <button
                v-else
                class="w-10 h-10 rounded-pill font-medium text-sm transition-colors duration-150"
                :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
                @click="goPage(pgn as number)"
              >{{ pgn }}</button>
            </template>
            <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
              <Icon name="heroicons:chevron-right" class="w-5 h-5" />
            </button>
          </nav>
        </div>
      </div>
    </div>
  </div>
</template>
