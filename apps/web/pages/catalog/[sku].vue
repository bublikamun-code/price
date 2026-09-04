<script setup lang="ts">
// Детальная карточка товара. См. SITEMAP.md §6.
// Реальные данные: GET /catalog/products/{sku}, /catalog/products/{sku}/price-history,
// соседи по серии — GET /catalog/products?series=<id>.
// Покупка: qty + «В корзину» через useCart (паритет с карточками каталога).
import type {
  CatalogPage,
  PriceHistoryItem,
  ProductCard,
  ProductDetail,
} from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const overlayDown = ref(false)
const { request } = useApi()
// карточка/лайтбокс — large; миниатюры — thumb (§16 п.17)
const { photoOf, thumbOf, urlOf } = useProductPhoto()

const sku = computed(() => String(route.params.sku))

const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const product = ref<ProductDetail | null>(null)
const history = ref<PriceHistoryItem[]>([])
const siblings = ref<ProductCard[]>([])
const lightbox = ref(false)

// Галерея: основное фото + дополнительные S3-ключи (ProductDetail.photos)
const gallery = computed(() =>
  [product.value?.photo_key, ...(product.value?.photos ?? [])].filter(Boolean) as string[],
)
const activePhoto = ref(0)
// URL активного фото (если gallery пуст — запасной вариант attributes.photo_url через photoOf)
const mainPhoto = computed(() =>
  gallery.value.length
    ? urlOf(gallery.value[activePhoto.value])
    : product.value ? photoOf(product.value) : null,
)

// Добавление в корзину прямо со страницы товара
// (то же поведение, что в каталоге: спиннер → «Добавлено» на 1.5 с).
const cart = useCart()
// Избранное: кнопка под «В корзину» (ленивая загрузка списка — внутри isFav/toggle).
const favorites = useFavorites()
const favError = ref('')
async function toggleFav() {
  if (!product.value) return
  favError.value = ''
  try {
    await favorites.toggle(product.value.sku)
  } catch (e) {
    favError.value = getErrorMessage(e, 'Не удалось обновить избранное')
  }
}
const qty = ref(1)
const adding = ref(false)
const added = ref(false)
const cartError = ref('')
let addedTimer: ReturnType<typeof setTimeout> | null = null

// Остаток товара: если известен — ограничиваем qty и показываем подсказку.
const maxQty = computed(() =>
  product.value?.stock_qty != null ? Math.max(0, product.value.stock_qty) : null,
)
const qtyHint = ref('')

function setQty(v: number) {
  let n = Math.max(1, Math.floor(v) || 1)
  if (maxQty.value != null && n > maxQty.value) {
    n = Math.max(1, maxQty.value)
    qtyHint.value = maxQty.value === 0
      ? 'Товара нет в наличии.'
      : `Доступно только ${maxQty.value} шт.`
  } else {
    qtyHint.value = ''
  }
  qty.value = n
}

async function addToCart() {
  if (adding.value || !product.value) return
  if (maxQty.value != null) {
    if (maxQty.value === 0) {
      qtyHint.value = 'Товара нет в наличии.'
      return
    }
    if (qty.value > maxQty.value) {
      setQty(qty.value)
      return
    }
  }
  adding.value = true
  cartError.value = ''
  try {
    await cart.add({ sku: product.value.sku, quantity: qty.value })
    added.value = true
    if (addedTimer) clearTimeout(addedTimer)
    addedTimer = setTimeout(() => {
      added.value = false
    }, 1500)
  } catch (e) {
    cartError.value = getErrorMessage(e, 'Не удалось добавить в корзину')
  } finally {
    adding.value = false
  }
}

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

// Характеристики и описание: утилиты из utils/attributes.ts (автоимпорт Nuxt).
// Служебные ключи (фото/описание) не выводим в списке характеристик.
const productDescription = computed(() => {
  const attrs = product.value?.attributes || {}
  const d = attrs.description
  return typeof d === 'string' && d.trim() ? d.trim() : ''
})

const attrEntries = computed<{ label: string; value: string }[]>(() => {
  const a = product.value?.attributes || {}
  return Object.entries(a)
    .filter(([k]) => !SERVICE_ATTR_KEYS.has(k))
    .map(([k, v]) => ({ label: getAttributeLabel(k), value: formatAttributeValue(k, v) }))
    .filter((row) => row.value && row.value !== '—')
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
  activePhoto.value = 0
  qty.value = 1
  qtyHint.value = ''
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
  if (addedTimer) clearTimeout(addedTimer)
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
          <NuxtLink :to="`/catalog?brand=${product.brand.id}`" class="hover:text-primary">{{ product.brand.name }}</NuxtLink>
        </template>
        <template v-if="product.series">
          <Icon name="heroicons:chevron-right" class="w-3.5 h-3.5 text-ink-faint" />
          <NuxtLink :to="`/catalog?series=${product.series.id}`" class="hover:text-primary">{{ product.series.name }}</NuxtLink>
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
        <div class="order-1 lg:order-none">
          <!-- Фото: компактнее, чтобы под ним без скролла помещалось описание -->
          <div class="card aspect-square lg:aspect-[4/3] overflow-hidden flex items-center justify-center relative">
            <img
              v-if="mainPhoto"
              :src="mainPhoto"
              :alt="product.name"
              class="w-full h-full object-contain cursor-zoom-in"
              @click="lightbox = true"
            >
            <Icon v-else name="heroicons:photo" class="w-20 h-20 text-ink-faint" />
            <button
              v-if="gallery.length > 1"
              type="button"
              aria-label="Предыдущее фото"
              class="absolute left-2 top-1/2 -translate-y-1/2 btn-ghost p-1.5 bg-black/30 text-white rounded-full hover:bg-black/50"
              @click="activePhoto = (activePhoto - 1 + gallery.length) % gallery.length"
            >
              <Icon name="heroicons:chevron-left" class="w-6 h-6" />
            </button>
            <button
              v-if="gallery.length > 1"
              type="button"
              aria-label="Следующее фото"
              class="absolute right-2 top-1/2 -translate-y-1/2 btn-ghost p-1.5 bg-black/30 text-white rounded-full hover:bg-black/50"
              @click="activePhoto = (activePhoto + 1) % gallery.length"
            >
              <Icon name="heroicons:chevron-right" class="w-6 h-6" />
            </button>
          </div>
          <!-- Миниатюры галереи -->
          <div v-if="gallery.length" class="flex flex-wrap gap-3 mt-3">
            <button
              v-for="(key, i) in gallery"
              :key="key"
              type="button"
              :aria-label="`Фото ${i + 1}`"
              class="w-20 h-20 rounded-card overflow-hidden border-2 bg-surface"
              :class="i === activePhoto ? 'border-primary' : 'border-transparent hover:border-primary/50'"
              @click="activePhoto = i"
            >
              <img
                :src="thumbOf(key)!"
                :alt="`${product.name} — фото ${i + 1}`"
                :loading="i === 0 ? undefined : 'lazy'"
                class="w-full h-full object-contain"
              >
            </button>
          </div>
        </div>

        <!-- Описание, характеристики, история и похожие: десктоп — под фото (col 1, row 2), мобильный — под блоком покупки -->
        <div class="order-3 lg:order-none lg:col-start-1 lg:row-start-2 flex flex-col gap-6 min-w-0">
          <!-- Описание -->
          <div v-if="productDescription">
            <h2 class="font-semibold mb-3">Описание</h2>
            <p class="text-sm text-ink-muted leading-relaxed panel p-5">{{ productDescription }}</p>
          </div>

          <!-- Характеристики (под фото) -->
          <div v-if="attrEntries.length">
            <h2 class="font-semibold mb-3">Характеристики</h2>
            <dl class="panel p-5 grid md:grid-cols-2 gap-x-8">
              <div
                v-for="row in attrEntries"
                :key="row.label"
                class="flex justify-between gap-4 py-2 border-b border-border"
              >
                <dt class="text-sm text-ink-muted shrink-0">{{ row.label }}</dt>
                <dd class="text-sm font-medium text-right break-all">{{ row.value }}</dd>
              </div>
            </dl>
          </div>

          <!-- График истории цены (левая колонка — правая при этом липнет до конца) -->
          <div v-if="history.length >= 2 && chart" class="card p-6">
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

          <!-- Соседи по серии (левая колонка) -->
          <div v-if="siblings.length">
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
                    v-if="thumbOf(s.photo_key)"
                    :src="thumbOf(s.photo_key)!"
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
                    {{ formatMoney(s.has_discount ? s.client_price : s.retail_price, s.currency) }}
                  </span>
                </div>
              </NuxtLink>
            </div>
          </div>
        </div>

        <!-- Инфо: липкий блок покупки на десктопе (левая колонка скролится, правая на месте, как в корзине); на мобильном — сразу под фото -->
        <div class="order-2 lg:order-none lg:col-start-2 lg:row-start-1 lg:row-span-2 lg:sticky lg:top-[88px] lg:self-start">
          <h1 class="text-2xl lg:text-3xl font-display font-bold mb-1">{{ product.name }}</h1>
          <p class="text-sm text-ink-muted mt-1 mb-4">Артикул: {{ product.sku }}</p>

          <div class="flex flex-wrap items-center gap-2 mb-5">
            <NuxtLink
              v-if="product.brand"
              :to="`/catalog?brand=${product.brand.id}`"
              class="chip bg-canvas text-ink-muted hover:text-primary transition-colors"
            >{{ product.brand.name }}</NuxtLink>
            <NuxtLink
              v-if="product.series"
              :to="`/catalog?series=${product.series.id}`"
              class="chip bg-canvas text-ink-muted hover:text-primary transition-colors"
            >{{ product.series.name }}</NuxtLink>
            <span :class="STOCK_META[product.stock_status]?.cls || 'badge-info'">
              {{ STOCK_META[product.stock_status]?.label || product.stock_status }}
            </span>
          </div>

          <!-- Цена -->
          <div class="card p-5 mb-5">
            <div class="flex items-baseline gap-2 flex-wrap">
              <template v-if="product.has_discount">
                <span class="text-3xl font-bold text-primary">{{ formatMoney(product.client_price, product.currency) }}</span>
                <span class="text-ink-muted line-through">{{ formatMoney(product.retail_price, product.currency) }}</span>
              </template>
              <template v-else>
                <span class="text-3xl font-bold">{{ formatMoney(product.retail_price, product.currency) }}</span>
              </template>
            </div>
            <p class="text-xs text-ink-faint mt-2">
              Источник курса: {{ rateSourceLabel(product.rate_source) }}
            </p>
            <div v-if="product.override_price != null" class="mt-3">
              <!-- override_price приходит из API как сырое значение прайса в BYN (§17),
                   в отличие от client_price/retail_price, сконвертированных в display-валюту -->
              <span class="badge-info">
                Фиксированная цена: {{ formatMoney(product.override_price, 'BYN') }}
              </span>
            </div>
          </div>

          <!-- Покупка: количество + добавление в корзину (как в карточках каталога) -->
          <div class="mb-5">
            <p v-if="maxQty != null" class="text-xs text-ink-muted mb-2">
              В наличии: {{ maxQty }} шт
            </p>
            <div class="flex items-center gap-3">
              <input
                type="number"
                min="1"
                :max="maxQty ?? undefined"
                :value="qty"
                aria-label="Количество"
                class="input py-2 w-20 text-center"
                @input="setQty(+($event.target as HTMLInputElement).value)"
              >
              <button class="btn-primary flex-1" :disabled="adding" @click="addToCart">
                <span v-if="adding" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                <Icon v-else-if="added" name="heroicons:check" class="w-4 h-4" />
                <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                {{ added ? 'Добавлено' : 'В корзину' }}
              </button>
            </div>
            <p v-if="qtyHint" class="text-xs text-warning mt-1.5">{{ qtyHint }}</p>
            <div v-if="cartError" class="badge-danger justify-center py-2 mt-2">{{ cartError }}</div>
            <button
              class="btn-outline w-full mt-3"
              :class="{ 'text-danger': favorites.isFav(product.sku) }"
              @click="toggleFav"
            >
              <Icon
                :name="favorites.isFav(product.sku) ? 'heroicons:heart-solid' : 'heroicons:heart'"
                class="w-4 h-4"
              />
              {{ favorites.isFav(product.sku) ? 'В избранном' : 'В избранное' }}
            </button>
            <div v-if="favError" class="badge-danger justify-center py-2 mt-2">{{ favError }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Lightbox -->
    <div
      v-if="lightbox && product && mainPhoto"
      class="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-8"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) lightbox = false; overlayDown = false"
    >
      <img
        :src="mainPhoto"
        :alt="product.name"
        class="max-h-[90vh] max-w-[90vw] object-contain"
      >
      <button class="absolute top-4 right-4 btn-ghost p-2 text-white" @click="lightbox = false">
        <Icon name="heroicons:x-mark" class="w-6 h-6" />
      </button>
    </div>
  </div>
</template>
