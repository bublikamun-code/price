<script setup lang="ts">
import { catalogProductIdSchema } from '~/domain/api/v2/catalog.schema'
import type { CatalogProduct } from '~/domain/api/v2/catalog.schema'
import type { FavoriteListPage, FavoriteRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Избранное' })

const { request } = useApi()
const cartV2 = useCartV2()
const favs = useFavorites()

const PER_PAGE = 12
const loading = ref(true)
const error = ref('')
const favorites = ref<FavoriteRead[]>([])
const total = ref(0)
const page = ref(1)
const removingSku = ref<string | null>(null)
const addingProductId = ref<string | null>(null)
const addedProductId = ref<string | null>(null)
const addAllLoading = ref(false)
const favQty = reactive<Record<string, number>>({})
const addResult = ref<{
  requested: number
  succeeded: number
  failed: Array<{ productId: string; sku: string; reason: string }>
} | null>(null)

const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / PER_PAGE)),
)
const cartLines = computed(() => cartV2.store.cart?.items ?? [])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await request<FavoriteListPage>('/api/v1/favorites', {
      query: { page: page.value, per_page: PER_PAGE },
    })
    favorites.value = response.data
    total.value = response.meta.total
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось загрузить избранное')
  } finally {
    loading.value = false
  }
}

async function removeFavorite(favorite: FavoriteRead) {
  removingSku.value = favorite.sku
  error.value = ''
  try {
    await favs.remove(favorite.sku)
    if (
      !favorites.value.some((item) => item.sku === favorite.sku) &&
      favorites.value.length === 1 &&
      page.value > 1
    ) {
      page.value -= 1
    }
    await load()
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось удалить из избранного')
  } finally {
    removingSku.value = null
  }
}

function getFavoriteQty(productId: string): number {
  return favQty[productId] ?? 1
}
function setFavoriteQty(productId: string, value: number) {
  favQty[productId] = Math.max(1, Math.floor(value) || 1)
}
function canonicalProductId(productId: string): string {
  return catalogProductIdSchema.parse(productId)
}
function cartQuantity(quantity: number): string {
  return String(Math.max(1, Math.floor(quantity) || 1))
}
function inCartQty(productId: string): number {
  return (
    cartLines.value.find((item) => item.productId === productId)?.quantity ?? 0
  )
}

let cartMutationQueue: Promise<unknown> = Promise.resolve()
function enqueueCartMutation<T>(operation: () => Promise<T>): Promise<T> {
  const result = cartMutationQueue.then(operation, operation)
  cartMutationQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}
async function readyCart() {
  const snapshot = await cartV2.ensureReady()
  if (!snapshot) throw new Error('Не удалось определить коммерческий контекст')
  return snapshot
}

async function addToCart(favorite: FavoriteRead) {
  if (addingProductId.value) return
  addingProductId.value = favorite.product_id
  error.value = ''
  try {
    await enqueueCartMutation(async () => {
      await readyCart()
      await cartV2.addItem({
        productId: canonicalProductId(favorite.product_id),
        quantity: cartQuantity(getFavoriteQty(favorite.product_id)),
      })
    })
    addedProductId.value = favorite.product_id
    setTimeout(() => {
      if (addedProductId.value === favorite.product_id)
        addedProductId.value = null
    }, 1500)
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось добавить в заявку')
  } finally {
    addingProductId.value = null
  }
}

async function addAllToCart() {
  if (addAllLoading.value || !favorites.value.length) return
  addAllLoading.value = true
  error.value = ''
  addResult.value = null
  const selected = [...favorites.value]
  const result = {
    requested: selected.length,
    succeeded: 0,
    failed: [] as Array<{ productId: string; sku: string; reason: string }>,
  }

  await enqueueCartMutation(async () => {
    try {
      await readyCart()
    } catch (cause) {
      const reason = getErrorMessage(cause, 'Не удалось подготовить заявку')
      result.failed = selected.map((favorite) => ({
        productId: favorite.product_id,
        sku: favorite.sku,
        reason,
      }))
      return
    }

    for (const favorite of selected) {
      try {
        const productId = canonicalProductId(favorite.product_id)
        await cartV2.addItem({
          productId,
          quantity: cartQuantity(getFavoriteQty(productId)),
        })
        result.succeeded += 1
      } catch (cause) {
        result.failed.push({
          productId: favorite.product_id,
          sku: favorite.sku,
          reason: getErrorMessage(cause, 'Не удалось добавить позицию'),
        })
      }
    }
  })

  addResult.value = result
  addAllLoading.value = false
}

function goPage(nextPage: number) {
  if (nextPage < 1 || nextPage > totalPages.value || nextPage === page.value)
    return
  page.value = nextPage
  addResult.value = null
  void load()
}

/** v1 отдаёт название бренда и статус без остатка — собираем форму v2-записи. */
function toRecordProduct(favorite: FavoriteRead): CatalogProduct {
  const currency = favorite.currency as CatalogProduct['clientPrice']['currency']
  const money = (amount: number) => ({ amount: amount.toFixed(2), currency })
  const archived = favorite.stock_status === 'ARCHIVED'
  return {
    id: favorite.product_id,
    sku: favorite.sku,
    name: favorite.name,
    brand: null,
    series: null,
    stockStatus: favorite.stock_status === 'PREORDER' ? 'PREORDER' : 'IN_STOCK',
    stockQuantity: archived ? 0 : null,
    attributes: {},
    basePrice: money(favorite.base_price_byn),
    retailPrice: money(favorite.retail_price),
    clientPrice: money(favorite.client_price),
    exchangeRate: { value: '1.0000', scale: 0, source: 'favorites' },
    hasDiscount: favorite.has_discount,
  }
}

function recordStock(favorite: FavoriteRead): string {
  if (favorite.stock_status === 'ARCHIVED') return 'Архив'
  if (favorite.stock_status === 'PREORDER') return 'Под заказ'
  return 'В наличии'
}

function recordComparePrice(favorite: FavoriteRead): string {
  if (!favorite.has_discount || favorite.client_price <= 0) return ''
  return formatMoney(favorite.retail_price, favorite.currency)
}

onMounted(() => {
  void load()
  void cartV2.ensureLoaded().catch(() => undefined)
})
</script>

<template>
  <div data-testid="favorites-page">
    <PageHeading
      eyebrow="Рабочий кабинет"
      title="Избранное"
      :description="loading ? 'Загрузка…' : `${total} ${pluralize(total, 'товар', 'товара', 'товаров')}`"
    >
      <template #actions>
        <UiButton
          v-if="favorites.length && !loading"
          size="touch"
          :loading="addAllLoading"
          :disabled="addAllLoading"
          data-testid="favorites-add-all"
          @click="addAllToCart"
        >
          <template #leading>
            <Icon name="heroicons:plus" class="size-4" aria-hidden="true" />
          </template>
          {{ addAllLoading ? 'Добавление…' : 'Добавить всё в заявку' }}
        </UiButton>
      </template>
    </PageHeading>

    <UiErrorState
      v-if="error"
      class="mb-5"
      title="Не удалось выполнить действие"
      :description="error"
      data-testid="favorites-error"
      @retry="load"
    />

    <div
      v-if="addResult"
      class="mb-5 border-y bg-surface px-4 py-3"
      :class="addResult.failed.length ? 'border-warning' : 'border-success'"
      role="status"
      data-testid="favorites-add-all-result"
    >
      <p class="text-sm font-medium">
        Добавлено {{ addResult.succeeded }} из {{ addResult.requested }}.
        <template v-if="addResult.failed.length">
          Не удалось: {{ addResult.failed.length }}.
        </template>
      </p>
      <ul v-if="addResult.failed.length" class="mt-2 space-y-1 text-xs text-ink-muted">
        <li v-for="failure in addResult.failed" :key="failure.productId">
          <span class="numeric">{{ failure.sku }}</span> — {{ failure.reason }}
        </li>
      </ul>
    </div>

    <UiLoadingState
      v-if="loading"
      class="min-h-64"
      label="Загрузка избранного"
    />

    <UiEmptyState
      v-else-if="!favorites.length"
      icon="heroicons:heart"
      title="В избранном пока пусто"
      description="Сохраняйте нужные товары, чтобы быстро вернуться к ним."
    >
      <template #action>
        <NuxtLink to="/catalog" class="btn-primary inline-flex min-h-11">Найти товары</NuxtLink>
      </template>
    </UiEmptyState>

    <div v-else data-testid="favorites-list">
      <ProductRecordRow
        v-for="favorite in favorites"
        :key="favorite.product_id"
        :product="toRecordProduct(favorite)"
        :quantity="getFavoriteQty(favorite.product_id)"
        :in-cart-quantity="inCartQty(favorite.product_id)"
        :loading="addingProductId === favorite.product_id"
        :added="addedProductId === favorite.product_id"
        :brand-name="favorite.brand_name || ''"
        :stock-label="recordStock(favorite)"
        :available="favorite.stock_status !== 'ARCHIVED'"
        :compare-price="recordComparePrice(favorite)"
        favorite
        test-id-prefix="favorite"
        @add="addToCart(favorite)"
        @favorite="removeFavorite(favorite)"
        @quantity-change="setFavoriteQty(favorite.product_id, $event)"
      />

      <UiPagination
        v-if="totalPages > 1"
        class="mt-6"
        :page="page"
        :page-count="totalPages"
        :total="total"
        label="Страницы избранного"
        @update:page="goPage"
      />
    </div>
  </div>
</template>
