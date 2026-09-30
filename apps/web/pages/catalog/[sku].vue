<script setup lang="ts">
import type { CatalogProduct } from '~/domain/api/v2/catalog.schema'
import type { ProductDocument } from '~/domain/api/v2/documents.schema'
import { catalogProductIdSchema } from '~/domain/api/v2/catalog.schema'
import { createCatalogRepository } from '~/domain/catalog/catalog.repository'

definePageMeta({ layout: 'client', middleware: 'auth' })

const route = useRoute()
const repository = createCatalogRepository(useApiV2())
const cartV2 = useCartV2()
const favorites = useFavorites()
// Скачивание PDF-документов (байты, не presigned — §16 п.38).
const {
  activeId: downloadingDocId,
  error: downloadError,
  downloadProductDocument,
} = useDocumentDownload()

const sku = computed(() => String(route.params.sku))
const product = ref<CatalogProduct | null>(null)
const siblings = ref<CatalogProduct[]>([])
const loading = ref(true)
const loadError = ref('')
const notFound = ref(false)

useHead({ title: computed(() => product.value?.name || 'Товар') })

function money(amount: string, currency: string): string {
  return formatMoney(amount, currency)
}
function rateSourceLabel(source: string): string {
  if (source === 'BYN') return 'Без конвертации (BYN)'
  if (source === 'FIXED') return 'По договору'
  if (source === 'NBRB') return 'Текущий курс НБ РБ'
  return source
}
function displayPrice(item: CatalogProduct) {
  if (Number(item.clientPrice.amount) > 0) return item.clientPrice
  if (Number(item.retailPrice.amount) > 0) return item.retailPrice
  return item.basePrice
}
function hasDisplayPrice(item: CatalogProduct): boolean {
  return Number(item.clientPrice.amount) > 0 || Number(item.retailPrice.amount) > 0
}
// Лестница скидок за объём бренда, по возрастанию порога (§16 п.41). Каталог
// публикует её целиком: количество строки известно только в корзине, поэтому
// цена выше остаётся за штуку без учёта объёма.
const volumeTiers = computed(() =>
  [...(product.value?.volumeTiers ?? [])].sort((a, b) => a.minQty - b.minQty),
)
const catalogMeta = computed(() => {
  const value = product.value
  if (!value) return ''
  return [value.brand?.name, value.series?.name].filter(Boolean).join(' · ') || 'Без бренда и серии'
})
const productDescription = computed(() => {
  const description = product.value?.attributes.description
  return typeof description === 'string' && description.trim() ? description.trim() : ''
})
const attrEntries = computed(() => {
  const attributes = product.value?.attributes ?? {}
  return Object.entries(attributes)
    .filter(([key]) => !SERVICE_ATTR_KEYS.has(key))
    .map(([key, value]) => ({ label: getAttributeLabel(key), value: formatAttributeValue(key, value) }))
    .filter((row) => row.value && row.value !== '—')
})

// Документы товара: свои + унаследованные из серии (scope=series). Просроченные
// (isExpired) не скрываются — показываются с красной пометкой «истёк» (§16 п.38).
const documents = computed<ProductDocument[]>(() => product.value?.documents ?? [])

async function downloadDocument(doc: ProductDocument) {
  if (!product.value || downloadingDocId.value) return
  await downloadProductDocument(product.value.id, doc.id, doc.fileName)
}

// Галерея детальной проекции: thumbnail (фото товара, иначе серии) плюс
// собственные фото товара из `media`. Выбранный кадр сбрасывается на
// репрезентативный при смене товара — иначе id прошлого кадра остался бы
// выбранным, а новый список не содержал бы его.
const selectedMediaId = ref<string | null>(null)
const galleryFrames = computed(() => {
  const frames = [product.value?.thumbnail ?? null, ...(product.value?.media ?? [])]
  const seen = new Set<string>()
  return frames.filter((frame): frame is NonNullable<typeof frame> => {
    if (!frame || seen.has(frame.id)) return false
    seen.add(frame.id)
    return true
  })
})
const activeMedia = computed(() => {
  const frames = galleryFrames.value
  return frames.find((frame) => frame.id === selectedMediaId.value) ?? frames[0] ?? null
})

const qty = ref(1)
const qtyHint = ref('')
const adding = ref(false)
const added = ref(false)
const cartError = ref('')
const favError = ref('')
let addedTimer: ReturnType<typeof setTimeout> | null = null
const maxQty = computed(() => product.value?.stockQuantity != null ? Math.max(0, product.value.stockQuantity) : null)
const cartQuantityInStore = computed(() => {
  if (!product.value) return 0
  return cartV2.store.cart?.items.find((item) => item.productId === product.value?.id)?.quantity ?? 0
})

function setQty(value: number) {
  let next = Math.max(1, Math.floor(value) || 1)
  if (maxQty.value != null && next > maxQty.value) {
    next = Math.max(1, maxQty.value)
    qtyHint.value = maxQty.value === 0 ? 'Товара нет в наличии.' : `Доступно только ${maxQty.value} шт.`
  } else {
    qtyHint.value = ''
  }
  qty.value = next
}
function stepQty(delta: number) {
  setQty(qty.value + delta)
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
async function addToCart() {
  if (adding.value || !product.value) return
  if (maxQty.value === 0) {
    qtyHint.value = 'Товара нет в наличии.'
    return
  }
  if (maxQty.value != null && qty.value > maxQty.value) {
    setQty(qty.value)
    return
  }
  adding.value = true
  cartError.value = ''
  try {
    await enqueueCartMutation(async () => {
      const snapshot = await cartV2.ensureReady()
      if (!snapshot) throw new Error('Не удалось определить коммерческий контекст')
      const productId = canonicalProductId(product.value!.id)
      await cartV2.addItem({ productId, quantity: cartQuantity(qty.value) })
    })
    added.value = true
    if (addedTimer) clearTimeout(addedTimer)
    addedTimer = setTimeout(() => { added.value = false }, 1500)
  } catch (cause) {
    cartError.value = getErrorMessage(cause, 'Не удалось добавить в заявку')
  } finally {
    adding.value = false
  }
}
async function toggleFavorite() {
  if (!product.value) return
  favError.value = ''
  try {
    await favorites.toggle(product.value.sku)
  } catch (cause) {
    favError.value = getErrorMessage(cause, 'Не удалось обновить избранное')
  }
}

let loadSeq = 0
let isUnmounted = false
async function load() {
  const seq = ++loadSeq
  loading.value = true
  loadError.value = ''
  notFound.value = false
  product.value = null
  siblings.value = []
  selectedMediaId.value = null
  qty.value = 1
  qtyHint.value = ''
  added.value = false
  downloadError.value = ''
  try {
    const result = await repository.getBySku(sku.value, 'fixed')
    if (seq !== loadSeq || isUnmounted) return
    product.value = result.product
    if (result.product.series) {
      try {
        const related = await repository.list({
          series: [result.product.series.id],
          sort: 'sku',
          limit: 8,
          priceCalcMode: 'fixed',
        })
        if (seq === loadSeq && !isUnmounted) {
          siblings.value = related.products.filter((item) => item.id !== result.product.id)
        }
      } catch {
        if (seq === loadSeq && !isUnmounted) siblings.value = []
      }
    }
  } catch (cause) {
    if (seq !== loadSeq || isUnmounted) return
    if (getErrorStatus(cause) === 404) notFound.value = true
    else loadError.value = getErrorMessage(cause, 'Не удалось загрузить товар')
  } finally {
    if (seq === loadSeq && !isUnmounted) loading.value = false
  }
}

onMounted(() => {
  void load()
  void cartV2.ensureLoaded().catch(() => undefined)
})
watch(sku, () => { void load() })
onUnmounted(() => {
  isUnmounted = true
  loadSeq += 1
  if (addedTimer) clearTimeout(addedTimer)
})
</script>

<template>
  <div class="min-w-0" data-testid="catalog-product-page">
    <nav class="mb-5 flex min-h-11 items-center gap-2 overflow-x-auto text-sm text-ink-muted" aria-label="Хлебные крошки">
      <NuxtLink to="/catalog" class="shrink-0 hover:text-action">Каталог</NuxtLink>
      <template v-if="product">
        <template v-if="product.brand">
          <Icon name="heroicons:chevron-right" class="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
          <NuxtLink :to="`/catalog?brand=${product.brand.id}`" class="shrink-0 hover:text-action">{{ product.brand.name }}</NuxtLink>
        </template>
        <template v-if="product.series">
          <Icon name="heroicons:chevron-right" class="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
          <NuxtLink :to="`/catalog?series=${product.series.id}`" class="shrink-0 hover:text-action">{{ product.series.name }}</NuxtLink>
        </template>
      </template>
    </nav>

    <div v-if="loading" class="space-y-5" aria-label="Загрузка товара" aria-busy="true">
      <UiSkeleton class="h-8 w-2/3" />
      <UiSkeleton class="h-40 w-full" />
      <UiSkeleton class="h-56 w-full" />
    </div>
    <UiEmptyState v-else-if="notFound" title="Товар не найден" description="Вернитесь в каталог и уточните артикул." icon="heroicons:archive-box-x-mark" data-testid="catalog-product-not-found">
      <template #action><NuxtLink to="/catalog" class="inline-flex min-h-11 items-center border border-border px-4 text-sm font-semibold">Вернуться в каталог</NuxtLink></template>
    </UiEmptyState>
    <UiErrorState v-else-if="loadError" title="Товар недоступен" :description="loadError" data-testid="catalog-product-error" @retry="load" />

    <article v-else-if="product" class="border border-border bg-surface">
      <header class="grid gap-5 border-b border-border p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <div class="min-w-0">
          <PageHeading
            class="mb-0"
            :eyebrow="product.sku"
            :title="product.name"
            :description="catalogMeta"
          >
            <template #actions>
              <StockBadge :status="product.stockStatus" size="md" />
              <span v-if="product.stockQuantity != null && product.stockQuantity <= 5" class="text-xs font-semibold text-warning-text">Осталось {{ product.stockQuantity }} шт.</span>
            </template>
          </PageHeading>
        </div>
        <div data-testid="catalog-product-media">
          <ProductPhoto
            :media="activeMedia"
            :alt="product.name"
            fit="contain"
            eager
            class="aspect-[4/3] w-full border border-border"
          />
          <p v-if="!activeMedia" class="mt-2 text-center text-xs leading-5 text-ink-muted" data-testid="catalog-media-placeholder">
            Фото товара пока недоступно
          </p>
          <div v-if="galleryFrames.length" class="mt-2 flex gap-2 overflow-x-auto scrollbar-none" role="group" aria-label="Фотографии товара">
            <button
              v-for="(frame, index) in galleryFrames"
              :key="frame.id"
              type="button"
              class="min-h-11 shrink-0 border p-0.5"
              :class="frame.id === activeMedia?.id ? 'border-action' : 'border-border'"
              :aria-label="`Показать фото ${index + 1} из ${galleryFrames.length}`"
              :aria-pressed="frame.id === activeMedia?.id"
              @click="selectedMediaId = frame.id"
            >
              <ProductPhoto :media="frame" :alt="`${product.name} — фото ${index + 1}`" class="size-14" />
            </button>
          </div>
        </div>
      </header>

      <section class="grid border-b border-border lg:grid-cols-2" aria-labelledby="product-price-title">
        <div class="border-b border-border p-4 sm:p-5 lg:border-b-0 lg:border-r">
          <h2 id="product-price-title" class="text-sm font-semibold text-ink-muted">Ваша цена</h2>
          <template v-if="!hasDisplayPrice(product)">
            <p class="mt-2 text-xl font-bold text-ink">Цена по запросу</p>
          </template>
          <template v-else-if="product.hasDiscount && Number(product.clientPrice.amount) > 0">
            <div class="mt-2 flex flex-wrap items-baseline gap-3">
              <strong class="numeric text-2xl font-bold text-action">{{ money(product.clientPrice.amount, product.clientPrice.currency) }}</strong>
              <span class="numeric text-sm text-ink-muted line-through">{{ money(product.retailPrice.amount, product.retailPrice.currency) }}</span>
            </div>
          </template>
          <template v-else>
            <strong class="numeric mt-2 block text-2xl font-bold text-ink">{{ money(displayPrice(product).amount, displayPrice(product).currency) }}</strong>
          </template>
          <dl class="mt-4 space-y-2 text-xs">
            <div class="flex justify-between gap-4"><dt class="text-ink-muted">Курс</dt><dd class="text-ink">{{ rateSourceLabel(product.exchangeRate.source) }}</dd></div>
            <div class="flex justify-between gap-4"><dt class="text-ink-muted">Базовая цена</dt><dd class="numeric text-ink">{{ money(product.basePrice.amount, product.basePrice.currency) }}</dd></div>
          </dl>

          <!-- Лестница объёмных скидок (§16 п.41). Цена выше — за штуку, без
               учёта объёма: количество строки известно только в корзине. -->
          <div v-if="volumeTiers.length" class="mt-4 border-t border-border pt-3">
            <p class="text-xs font-semibold text-ink-muted">Скидка за объём</p>
            <ul class="mt-2 space-y-1.5">
              <li v-for="tier in volumeTiers" :key="tier.minQty" class="flex items-center justify-between gap-3 text-xs">
                <span class="text-ink-muted">от {{ tier.minQty }} шт</span>
                <span class="numeric font-semibold text-success-text">минус {{ formatPercent(tier.discountPercent) }}</span>
              </li>
            </ul>
            <p class="mt-2 text-xs text-ink-faint">
              Скидка считается от количества в одной позиции заявки. Применяется одна ступень — та,
              порог которой уже достигнут.
            </p>
          </div>
        </div>

        <div class="p-4 sm:p-5">
          <h2 class="text-sm font-semibold text-ink-muted">Добавить в заявку</h2>
          <p v-if="maxQty != null" class="mt-2 text-xs text-ink-muted">Доступно: {{ maxQty }} шт.</p>
          <p v-if="cartQuantityInStore" class="mt-1 text-xs font-semibold text-success-text">В текущей заявке: {{ cartQuantityInStore }} шт.</p>
          <div class="mt-4 flex flex-col gap-3 sm:flex-row">
            <div class="flex h-11 w-36 shrink-0 items-center border border-border" role="group" aria-label="Количество">
              <button type="button" class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="qty <= 1 || maxQty === 0" aria-label="Уменьшить количество" data-testid="catalog-product-qty-decrease" @click="stepQty(-1)"><Icon name="heroicons:minus" class="size-4" /></button>
              <label for="catalog-product-quantity" class="sr-only">Количество</label>
              <input id="catalog-product-quantity" :value="qty" type="number" inputmode="numeric" min="1" :max="maxQty ?? undefined" class="numeric w-12 bg-transparent text-center text-sm outline-none" data-testid="catalog-product-quantity" @input="setQty(+($event.target as HTMLInputElement).value)">
              <button type="button" class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="maxQty != null && qty >= maxQty" aria-label="Увеличить количество" data-testid="catalog-product-qty-increase" @click="stepQty(1)"><Icon name="heroicons:plus" class="size-4" /></button>
            </div>
            <UiButton class="flex-1" size="touch" :loading="adding" :disabled="maxQty === 0" :data-testid="`catalog-product-add-${product.id}`" @click="addToCart">
              <template #leading><Icon :name="added ? 'heroicons:check' : 'heroicons:shopping-cart'" class="size-4" /></template>
              {{ maxQty === 0 ? 'Нет в наличии' : added ? 'Добавлено' : 'Добавить в заявку' }}
            </UiButton>
          </div>
          <p v-if="qtyHint" class="mt-2 text-xs text-warning-text">{{ qtyHint }}</p>
          <p v-if="cartError" class="mt-2 text-xs text-danger-text" role="alert">{{ cartError }}</p>
          <UiButton variant="outline" size="touch" class="mt-3 w-full" :aria-pressed="favorites.isFav(product.sku)" :data-testid="`catalog-product-favorite-${product.id}`" @click="toggleFavorite">
            <template #leading><Icon :name="favorites.isFav(product.sku) ? 'heroicons:heart-solid' : 'heroicons:heart'" class="size-4" /></template>
            {{ favorites.isFav(product.sku) ? 'В избранном' : 'В избранное' }}
          </UiButton>
          <p v-if="favError" class="mt-2 text-xs text-danger-text" role="alert">{{ favError }}</p>
        </div>
      </section>

      <section v-if="productDescription" class="border-b border-border p-4 sm:p-5" aria-labelledby="product-description-title">
        <h2 id="product-description-title" class="text-lg font-bold text-ink">Описание</h2>
        <p class="mt-3 whitespace-pre-line text-sm leading-6 text-ink-muted">{{ productDescription }}</p>
      </section>

      <section v-if="attrEntries.length" class="border-b border-border p-4 sm:p-5" aria-labelledby="product-specs-title">
        <h2 id="product-specs-title" class="text-lg font-bold text-ink">Характеристики</h2>
        <dl class="mt-3 grid border-t border-border sm:grid-cols-2 sm:gap-x-8">
          <div v-for="row in attrEntries" :key="row.label" class="grid grid-cols-[minmax(8rem,0.7fr)_minmax(0,1fr)] gap-4 border-b border-border py-2.5 text-sm">
            <dt class="text-ink-muted">{{ row.label }}</dt><dd class="break-words text-right font-medium text-ink">{{ row.value }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="documents.length" class="border-b border-border p-4 sm:p-5" aria-labelledby="product-documents-title" data-testid="catalog-product-documents">
        <h2 id="product-documents-title" class="text-lg font-bold text-ink">Документы</h2>
        <ul class="mt-3 border-t border-border">
          <li
            v-for="doc in documents"
            :key="doc.id"
            class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border py-2.5 text-sm"
            :data-testid="`catalog-product-document-${doc.id}`"
          >
            <span class="badge" :class="doc.type === 'CERTIFICATE' ? 'badge-info' : ''">{{ doc.type === 'CERTIFICATE' ? 'Сертификат' : 'Даташит' }}</span>
            <span class="min-w-0 flex-1 basis-40 truncate font-medium text-ink" :title="doc.fileName">{{ doc.fileName }}</span>
            <span v-if="doc.scope === 'series'" class="text-xs text-ink-muted">общий для серии</span>
            <span v-if="doc.validUntil && !doc.isExpired" class="badge-success">действует до {{ formatDate(doc.validUntil) }}</span>
            <span v-else-if="doc.isExpired" class="badge-danger">истёк{{ doc.validUntil ? ` ${formatDate(doc.validUntil)}` : '' }}</span>
            <UiButton
              variant="outline"
              size="compact"
              :loading="downloadingDocId === doc.id"
              :disabled="downloadingDocId !== null && downloadingDocId !== doc.id"
              :data-testid="`catalog-product-document-download-${doc.id}`"
              @click="downloadDocument(doc)"
            >
              <template #leading><Icon name="heroicons:arrow-down-tray" class="size-4" /></template>
              Скачать
            </UiButton>
          </li>
        </ul>
        <p v-if="downloadError" class="mt-2 text-xs text-danger-text" role="alert" data-testid="catalog-product-documents-error">{{ downloadError }}</p>
      </section>

      <section v-if="siblings.length" class="p-4 sm:p-5" aria-labelledby="product-related-title">
        <div class="mb-3 flex items-end justify-between gap-4">
          <div>
            <p class="text-xs font-semibold text-ink-muted">Продолжение серии</p>
            <h2 id="product-related-title" class="mt-1 text-lg font-bold text-ink">Похожие товары</h2>
          </div>
          <NuxtLink v-if="product.series" :to="`/catalog?series=${product.series.id}`" class="inline-flex min-h-11 items-center text-sm font-semibold text-action hover:underline">Вся серия</NuxtLink>
        </div>
        <div class="border-t border-border">
          <NuxtLink v-for="item in siblings" :key="item.id" :to="`/catalog/${encodeURIComponent(item.sku)}`" class="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-border py-3 hover:bg-surface-2 sm:grid-cols-[8rem_minmax(0,1fr)_8rem]">
            <span class="numeric text-xs text-ink-muted">{{ item.sku }}</span>
            <span class="min-w-0 truncate text-sm font-semibold text-ink">{{ item.name }}</span>
            <span class="numeric text-right text-sm text-ink">{{ hasDisplayPrice(item) ? money(displayPrice(item).amount, displayPrice(item).currency) : 'По запросу' }}</span>
          </NuxtLink>
        </div>
      </section>
    </article>
  </div>
</template>
