<script setup lang="ts">
import type {
  CatalogFacets,
  CatalogListQuery,
  CatalogProduct,
  CatalogSort,
  CatalogStockStatus,
} from '~/domain/api/v2/catalog.schema'
import { catalogProductIdSchema } from '~/domain/api/v2/catalog.schema'
import { createCatalogRepository } from '~/domain/catalog/catalog.repository'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Каталог' })

const route = useRoute()
const router = useRouter()
const repository = createCatalogRepository(useApiV2())
const cartV2 = useCartV2()
const favorites = useFavorites()
const auth = useAuth()
const sessionContext = useSessionContext()

const PER_PAGE = 20
const sortOptions: Array<{ value: CatalogSort; label: string }> = [
  { value: 'name', label: 'Название А→Я' },
  { value: '-name', label: 'Название Я→А' },
  { value: 'price', label: 'Цена по возрастанию' },
  { value: '-price', label: 'Цена по убыванию' },
  { value: 'sku', label: 'Артикул' },
]

function idsFromQuery(key: string): string[] {
  const value = route.query[key]
  if (!value) return []
  const raw = Array.isArray(value) ? value : [String(value)]
  return raw.flatMap((item) => String(item).split(',')).filter(Boolean)
}

const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
// Один объект состояния на всю панель фильтров: ею владеют и десктопный рельс,
// и мобильная шторка, а страница читает её при построении запроса и URL.
const filters = reactive<{
  brands: string[]
  series: string[]
  stock: CatalogStockStatus | ''
  model: string
}>({
  brands: idsFromQuery('brand'),
  series: idsFromQuery('series'),
  stock:
    route.query.stock === 'IN_STOCK' || route.query.stock === 'PREORDER' ? route.query.stock : '',
  model: typeof route.query.model === 'string' ? route.query.model : '',
})
const sort = ref<CatalogSort>(
  sortOptions.some((option) => option.value === route.query.sort)
    ? (route.query.sort as CatalogSort)
    : 'name',
)
/** UiSelect отдаёт string | number, а набор значений зафиксирован в sortOptions. */
const sortModel = computed({
  get: () => sort.value as string | number,
  set: (value: string | number) => {
    sort.value = value as CatalogSort
  },
})
const currentCursor = ref(typeof route.query.cursor === 'string' ? route.query.cursor : '')
const previousCursors = ref<string[]>([])
const page = ref(1)

const products = ref<CatalogProduct[]>([])
const facets = ref<CatalogFacets>({ brands: [], series: [], stockStatuses: [], models: [] })
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const loading = ref(true)
const firstLoadDone = ref(false)
const loadError = ref('')
const mutationError = ref('')
const drawerOpen = ref(false)
const qtyMap = reactive<Record<string, number>>({})
const addingProductId = ref<string | null>(null)
const addedProductId = ref<string | null>(null)

const firstName = computed(() => auth.user?.name?.trim().split(/\s+/)[0] || 'клиент')
const activeOrganization = computed(() => {
  const context = sessionContext.store.context
  if (!context) return auth.user?.company || 'Каталог'
  if (context.commercialScope === 'USER') return 'Личная заявка'
  return context.memberships.find((item) => item.organizationId === context.organizationId)?.displayName
    || context.memberships.find((item) => item.organizationId === context.organizationId)?.legalName
    || 'Ваши условия'
})
const categoryTabs = computed(() => facets.value.brands.slice(0, 5))
const modelOptions = computed(() => [
  { value: '', label: 'Все модели' },
  ...facets.value.models.map((model) => ({ value: model, label: model })),
])
const cartLines = computed(() => cartV2.store.cart?.items ?? [])
const activeFilterCount = computed(() => {
  return filters.brands.length
    + filters.series.length
    + (filters.stock ? 1 : 0)
    + (filters.model ? 1 : 0)
})
function hasPositivePrice(product: CatalogProduct): boolean {
  return Number(product.clientPrice.amount) > 0
}
function inCartQty(productId: string): number {
  return cartLines.value.find((item) => item.productId === productId)?.quantity ?? 0
}
function getQty(product: CatalogProduct): number {
  return qtyMap[product.id] ?? Math.max(1, inCartQty(product.id))
}
function setQty(product: CatalogProduct, value: number) {
  let quantity = Math.max(1, Math.floor(value) || 1)
  if (product.stockQuantity != null && product.stockQuantity > 0) {
    quantity = Math.min(quantity, product.stockQuantity)
  }
  qtyMap[product.id] = quantity
}
function selectCategory(brandId: string) {
  filters.brands = brandId ? [brandId] : []
  resetPosition()
  void load()
}

let loadSeq = 0
let isUnmounted = false
let facetsLoaded = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

async function load() {
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''

  const urlQuery: Record<string, string> = {}
  if (q.value) urlQuery.q = q.value
  if (filters.brands.length) urlQuery.brand = filters.brands.join(',')
  if (filters.series.length) urlQuery.series = filters.series.join(',')
  if (filters.stock) urlQuery.stock = filters.stock
  if (filters.model) urlQuery.model = filters.model
  if (sort.value !== 'name') urlQuery.sort = sort.value
  if (currentCursor.value) urlQuery.cursor = currentCursor.value
  void router.replace({ query: urlQuery }).catch(() => {})

  const query: Omit<CatalogListQuery, 'q'> = {
    brands: filters.brands.length ? filters.brands : undefined,
    series: filters.series.length ? filters.series : undefined,
    stock: filters.stock || undefined,
    model: filters.model || undefined,
    sort: sort.value,
    limit: PER_PAGE,
    cursor: currentCursor.value || undefined,
    priceCalcMode: 'fixed',
  }
  const catalogRequest = q.value ? repository.search(q.value, query) : repository.list({ q: q.value || undefined, ...query })
  const facetsRequest = facetsLoaded ? Promise.resolve(null) : repository.getFacets()

  try {
    const [catalogOutcome, facetsOutcome] = await Promise.allSettled([catalogRequest, facetsRequest])
    if (seq !== loadSeq || isUnmounted) return
    if (catalogOutcome.status === 'fulfilled') {
      products.value = catalogOutcome.value.products
      nextCursor.value = catalogOutcome.value.nextCursor
      hasMore.value = catalogOutcome.value.hasMore
    } else {
      loadError.value = getErrorMessage(catalogOutcome.reason, 'Не удалось загрузить каталог')
    }
    if (facetsOutcome.status === 'fulfilled' && facetsOutcome.value) {
      facets.value = facetsOutcome.value.facets
      facetsLoaded = true
    }
  } finally {
    if (seq === loadSeq && !isUnmounted) {
      loading.value = false
      firstLoadDone.value = true
    }
  }
}

function resetPosition() {
  currentCursor.value = ''
  previousCursors.value = []
  page.value = 1
}
function applyFilters() {
  resetPosition()
  void load()
}
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(applyFilters, 300)
}
function resetFilters() {
  q.value = ''
  filters.brands = []
  filters.series = []
  filters.stock = ''
  filters.model = ''
  sort.value = 'name'
  resetPosition()
  void load()
}
function goNext() {
  if (!nextCursor.value) return
  previousCursors.value.push(currentCursor.value)
  currentCursor.value = nextCursor.value
  page.value += 1
  void load()
}
function goPrevious() {
  if (!previousCursors.value.length) return
  currentCursor.value = previousCursors.value.pop() ?? ''
  page.value = Math.max(1, page.value - 1)
  void load()
}

function canonicalProductId(productId: string): string {
  return catalogProductIdSchema.parse(productId)
}
function cartQuantity(quantity: number): string {
  return String(Math.max(1, Math.floor(quantity) || 1))
}
let cartMutationQueue: Promise<unknown> = Promise.resolve()
function enqueueCartMutation<T>(operation: () => Promise<T>): Promise<T> {
  const result = cartMutationQueue.then(operation, operation)
  cartMutationQueue = result.then(() => undefined, () => undefined)
  return result
}
async function readyCart() {
  const snapshot = await cartV2.ensureReady()
  if (!snapshot) throw new Error('Не удалось определить коммерческий контекст')
  return snapshot
}
async function addToCart(product: CatalogProduct) {
  if (addingProductId.value || product.stockQuantity === 0) return
  addingProductId.value = product.id
  mutationError.value = ''
  try {
    await enqueueCartMutation(async () => {
      await readyCart()
      const productId = canonicalProductId(product.id)
      const quantity = cartQuantity(getQty(product))
      const existing = cartV2.store.cart?.items.find((item) => item.productId === productId)
      if (existing) await cartV2.replaceItem(productId, { quantity })
      else await cartV2.addItem({ productId, quantity })
      qtyMap[productId] = Number(quantity)
    })
    addedProductId.value = product.id
    setTimeout(() => {
      if (addedProductId.value === product.id) addedProductId.value = null
    }, 1500)
  } catch (cause) {
    mutationError.value = getErrorMessage(cause, 'Не удалось добавить в заявку')
  } finally {
    addingProductId.value = null
  }
}
async function toggleFavorite(sku: string) {
  mutationError.value = ''
  try {
    await favorites.toggle(sku)
  } catch (cause) {
    mutationError.value = getErrorMessage(cause, 'Не удалось обновить избранное')
  }
}

onMounted(() => {
  void load()
  void Promise.allSettled([cartV2.ensureLoaded(), sessionContext.ensureLoaded()])
})
onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div class="min-w-0" data-testid="catalog-page">
    <PageHeading
      :eyebrow="activeOrganization || 'Каталог'"
      :title="`Добрый день, ${firstName}.`"
      description="Найдите товар по артикулу, бренду или названию."
    >
      <template #actions>
        <div class="relative w-full lg:max-w-md">
          <Icon name="heroicons:magnifying-glass" class="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
          <label for="catalog-search" class="sr-only">Поиск по каталогу</label>
          <input
            id="catalog-search"
            v-model="q"
            type="search"
            class="min-h-11 w-full border border-border-strong bg-surface py-2 pl-10 pr-10 text-sm text-ink placeholder:text-ink-muted"
            placeholder="Найти товар, бренд или артикул"
            data-testid="catalog-search"
            @input="onSearchInput"
            @keyup.enter="applyFilters"
          >
          <UiSpinner v-if="loading" class="absolute right-3 top-1/2 -translate-y-1/2" :size="16" />
        </div>
      </template>
    </PageHeading>

    <section class="mt-5" aria-label="Быстрые действия">
      <div class="grid border-y border-border sm:grid-cols-3">
        <NuxtLink to="/bulk-add" class="flex min-h-11 items-center gap-3 border-b border-border px-3 py-2 text-sm font-semibold text-ink hover:text-action sm:border-b-0 sm:border-r">
          <Icon name="heroicons:document-plus" class="size-4 text-ink-muted" aria-hidden="true" />
          Добавить спецификацию
        </NuxtLink>
        <NuxtLink to="/orders" class="flex min-h-11 items-center gap-3 border-b border-border px-3 py-2 text-sm font-semibold text-ink hover:text-action sm:border-b-0 sm:border-r">
          <Icon name="heroicons:arrow-path" class="size-4 text-ink-muted" aria-hidden="true" />
          Повторить заявку
        </NuxtLink>
        <NuxtLink to="/cart" class="flex min-h-11 items-center gap-3 px-3 py-2 text-sm font-semibold text-ink hover:text-action">
          <Icon name="heroicons:shopping-cart" class="size-4 text-ink-muted" aria-hidden="true" />
          Текущая заявка
          <span v-if="cartV2.store.cart" class="numeric ml-auto text-xs text-ink-muted">{{ cartV2.store.cart.totalItems }} поз.</span>
        </NuxtLink>
      </div>
    </section>

    <section class="mt-6" aria-labelledby="catalog-categories-title">
      <div class="mb-2 flex items-center justify-between gap-4">
        <h2 id="catalog-categories-title" class="text-lg font-bold text-ink">Категории</h2>
        <p class="numeric text-xs text-ink-muted" aria-live="polite">Показано: {{ products.length }}</p>
      </div>
      <div class="scrollbar-none flex overflow-x-auto border-b border-border" role="tablist" aria-label="Категории каталога">
        <button
          type="button"
          role="tab"
          class="min-h-11 shrink-0 border-b-2 border-transparent px-4 text-sm font-semibold text-ink-muted"
          :class="!filters.brands.length ? 'border-action text-ink' : 'hover:text-ink'"
          :aria-selected="!filters.brands.length"
          @click="selectCategory('')"
        >
          Все
        </button>
        <button
          v-for="brand in categoryTabs"
          :key="brand.id"
          type="button"
          role="tab"
          class="min-h-11 shrink-0 border-b-2 border-transparent px-4 text-sm font-semibold text-ink-muted"
          :class="filters.brands.includes(brand.id) ? 'border-action text-ink' : 'hover:text-ink'"
          :aria-selected="filters.brands.includes(brand.id)"
          @click="selectCategory(brand.id)"
        >
          {{ brand.name }}
        </button>
      </div>
    </section>

    <div v-if="loadError" class="mt-5 border border-danger/50 bg-danger-soft p-4" role="alert" data-testid="catalog-error">
      <p class="text-sm text-danger-text">{{ loadError }}</p>
      <button type="button" class="mt-2 min-h-11 text-sm font-semibold text-danger-text hover:underline" @click="load">Повторить</button>
    </div>
    <div v-if="mutationError" class="mt-5 border border-danger/50 bg-danger-soft px-4 py-3 text-sm text-danger-text" role="alert">{{ mutationError }}</div>

    <div class="mt-5 flex items-start gap-5">
      <aside
        class="hidden w-72 shrink-0 self-start border border-border bg-surface lg:sticky lg:top-24 lg:block"
        aria-label="Фильтры каталога"
        data-testid="catalog-filters"
      >
        <div class="flex items-center gap-2 border-b border-border px-4 py-3">
          <h2 class="font-bold text-ink">Фильтры</h2>
          <span
            v-if="activeFilterCount"
            class="numeric border border-action bg-action-soft px-1.5 py-0.5 text-xs font-semibold text-action"
          >{{ activeFilterCount }}</span>
          <p class="ml-auto text-xs text-ink-muted">Уточните состав каталога</p>
        </div>
        <CatalogFilters
          :filters="filters"
          :facets="facets"
          :model-options="modelOptions"
          instance="rail"
          @update:brands="filters.brands = $event"
          @update:series="filters.series = $event"
          @update:stock="filters.stock = $event"
          @update:model-value="filters.model = $event"
          @change="applyFilters"
          @reset="resetFilters"
        />
      </aside>

      <UiSheet
        v-model:open="drawerOpen"
        side="bottom"
        title="Фильтры"
        :description="activeFilterCount ? `Выбрано фильтров: ${activeFilterCount}` : 'Уточните состав каталога'"
      >
        <CatalogFilters
          :filters="filters"
          :facets="facets"
          :model-options="modelOptions"
          instance="sheet"
          @update:brands="filters.brands = $event"
          @update:series="filters.series = $event"
          @update:stock="filters.stock = $event"
          @update:model-value="filters.model = $event"
          @change="applyFilters"
          @reset="resetFilters"
        />
        <template #footer>
          <UiButton size="touch" class="w-full" data-testid="catalog-filters-apply" @click="drawerOpen = false">
            Показать {{ products.length }} {{ pluralize(products.length, 'товар', 'товара', 'товаров') }}
          </UiButton>
        </template>
      </UiSheet>

      <section class="min-w-0 flex-1" aria-label="Товары каталога">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <button type="button" class="inline-flex min-h-11 items-center gap-2 border border-border px-3 text-sm font-semibold text-ink lg:hidden" aria-haspopup="dialog" :aria-expanded="drawerOpen" data-testid="catalog-filters-open" @click="drawerOpen = true">
            <Icon name="heroicons:funnel" class="size-4" aria-hidden="true" /> Фильтры
            <span v-if="activeFilterCount" class="numeric border border-action bg-action-soft px-1.5 py-0.5 text-xs text-action">{{ activeFilterCount }}</span>
          </button>
          <p class="hidden text-xs text-ink-muted sm:block">Сортировка применяется на сервере</p>
          <UiField for="catalog-sort" label="Сортировка" class="ml-auto w-56">
            <UiSelect v-model="sortModel" :options="sortOptions" @update:model-value="applyFilters" />
          </UiField>
        </div>

        <div v-if="loading && !firstLoadDone" class="border-t border-border" aria-busy="true" aria-label="Загрузка каталога">
          <div v-for="index in 8" :key="index" class="grid gap-3 border-b border-border py-4 sm:grid-cols-[5rem_minmax(0,1fr)_8rem_8rem]">
            <UiSkeleton class="size-16" /><div class="space-y-2"><UiSkeleton class="h-4 w-1/3" /><UiSkeleton class="h-5 w-3/4" /></div><UiSkeleton class="hidden h-8 sm:block" /><UiSkeleton class="hidden h-8 sm:block" />
          </div>
        </div>
        <UiEmptyState v-else-if="loadError && !products.length" title="Каталог недоступен" description="Проверьте соединение и повторите запрос." icon="heroicons:exclamation-triangle">
          <template #action><button type="button" class="inline-flex min-h-11 items-center border border-border px-4 text-sm font-semibold" @click="load">Повторить</button></template>
        </UiEmptyState>
        <UiEmptyState v-else-if="!products.length" title="Ничего не найдено" description="Измените условия поиска или сбросьте фильтры." icon="heroicons:archive-box-x-mark">
          <template #action><button type="button" class="inline-flex min-h-11 items-center border border-border px-4 text-sm font-semibold" @click="resetFilters">Сбросить фильтры</button></template>
        </UiEmptyState>

        <template v-else>
          <div class="lg:hidden" :class="loading ? 'pointer-events-none opacity-60' : ''" data-testid="catalog-records">
            <ProductRecordRow
              v-for="product in products"
              :key="product.id"
              :product="product"
              :quantity="getQty(product)"
              :in-cart-quantity="inCartQty(product.id)"
              :loading="addingProductId === product.id"
              :added="addedProductId === product.id"
              :favorite="favorites.isFav(product.sku)"
              @add="addToCart(product)"
              @favorite="toggleFavorite(product.sku)"
              @quantity-change="setQty(product, $event)"
            />
          </div>

          <div class="hidden border-t border-border bg-surface lg:block" :class="loading ? 'pointer-events-none opacity-60' : ''" data-testid="catalog-table">
            <UiTableFrame caption="Каталог товаров" overflow-label="Каталог товаров">
              <template #header>
                <tr class="border-b border-border bg-surface-2 text-xs font-semibold text-ink-muted">
                  <th scope="col" class="w-36 px-3 py-2">Артикул</th>
                  <th scope="col" class="px-3 py-2">Товар</th>
                  <th scope="col" class="w-32 px-3 py-2">Наличие</th>
                  <th scope="col" class="w-32 px-3 py-2 text-right">Цена</th>
                  <th scope="col" class="w-32 px-3 py-2 text-center">Количество</th>
                  <th scope="col" class="w-32 px-3 py-2 text-right">Действие</th>
                </tr>
              </template>
              <template v-for="product in products" :key="product.id">
                <tr class="min-h-12 border-b border-border hover:bg-surface-2" :data-testid="`catalog-row-${product.id}`">
                  <td class="numeric max-w-0 truncate px-3 py-2 text-xs text-ink" :title="product.sku">{{ product.sku }}</td>
                  <td class="max-w-0 px-3 py-2">
                    <NuxtLink :to="`/catalog/${encodeURIComponent(product.sku)}`" class="block truncate text-sm font-semibold text-ink hover:text-action" :title="product.name">{{ product.name }}</NuxtLink>
                    <span class="block truncate text-xs text-ink-muted">{{ product.brand?.name || 'Без бренда' }}<template v-if="product.series"> · {{ product.series.name }}</template></span>
                  </td>
                  <td class="px-3 py-2">
                    <StockBadge
                      :status="product.stockStatus"
                      :quantity="product.stockStatus === 'IN_STOCK' ? product.stockQuantity : null"
                    />
                  </td>
                  <td class="numeric whitespace-nowrap px-3 py-2 text-right">
                    <template v-if="hasPositivePrice(product)">
                      <strong class="block text-sm text-ink">{{ formatMoney(product.clientPrice.amount, product.clientPrice.currency) }}</strong>
                      <span v-if="product.hasDiscount" class="block text-xs text-ink-muted line-through">{{ formatMoney(product.retailPrice.amount, product.retailPrice.currency) }}</span>
                    </template>
                    <span v-else class="text-xs text-ink-muted">По запросу</span>
                  </td>
                  <td class="px-3 py-2">
                    <div class="mx-auto flex h-9 w-28 items-center border border-border" role="group" :aria-label="`Количество товара «${product.name}»`">
                      <button type="button" class="flex size-9 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="getQty(product) <= 1" :aria-label="`Уменьшить количество товара «${product.name}»`" @click="setQty(product, getQty(product) - 1)"><Icon name="heroicons:minus" class="size-3.5" /></button>
                      <span class="numeric w-7 text-center text-xs font-semibold">{{ getQty(product) }}</span>
                      <button type="button" class="flex size-9 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="product.stockQuantity != null && getQty(product) >= product.stockQuantity" :aria-label="`Увеличить количество товара «${product.name}»`" @click="setQty(product, getQty(product) + 1)"><Icon name="heroicons:plus" class="size-3.5" /></button>
                    </div>
                  </td>
                  <td class="px-3 py-2 text-right">
                    <UiButton size="compact" :loading="addingProductId === product.id" :disabled="product.stockQuantity === 0" :aria-label="`${inCartQty(product.id) ? 'Обновить' : 'Добавить'} товар «${product.name}»`" :data-testid="`catalog-add-${product.id}`" @click="addToCart(product)">
                      <Icon v-if="!addingProductId" :name="addedProductId === product.id || inCartQty(product.id) ? 'heroicons:check' : 'heroicons:plus'" class="size-4" />
                      {{ addedProductId === product.id ? 'Готово' : inCartQty(product.id) ? 'Обновить' : 'Добавить' }}
                    </UiButton>
                  </td>
                </tr>
              </template>
            </UiTableFrame>
          </div>

          <nav v-if="hasMore || previousCursors.length" class="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4" aria-label="Курсорная пагинация каталога" data-testid="catalog-pagination">
            <UiButton variant="outline" :disabled="!previousCursors.length || loading" data-testid="catalog-previous" @click="goPrevious">
              <template #leading><Icon name="heroicons:chevron-left" class="size-4" /></template> Назад
            </UiButton>
            <span class="numeric text-xs text-ink-muted">Группа {{ page }}</span>
            <UiButton :disabled="!nextCursor || loading" data-testid="catalog-next" @click="goNext">
              Показать ещё <template #trailing><Icon name="heroicons:arrow-right" class="size-4" /></template>
            </UiButton>
          </nav>
        </template>
      </section>
    </div>
  </div>
</template>
