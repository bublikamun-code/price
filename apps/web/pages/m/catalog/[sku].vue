<script setup lang="ts">
// Мобильная карточка товара (Mini App): фото, цена, количество, «В корзину».
import type { ProductDetail } from '~/types/api'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
const route = useRoute()
const router = useRouter()
const { request } = useApi()
const { photoOf } = useProductPhoto()
const cart = useCart()

const sku = computed(() => String(route.params.sku))
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const product = ref<ProductDetail | null>(null)
const qty = ref(1)
const adding = ref(false)
const added = ref(false)
const addError = ref('')
let addedTimer: ReturnType<typeof setTimeout> | null = null

useHead({ title: computed(() => product.value?.name || 'Товар') })

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  product.value = null
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
  } finally {
    loading.value = false
  }
}

async function addToCart() {
  if (adding.value || !product.value) return
  adding.value = true
  addError.value = ''
  try {
    await cart.add({ sku: product.value.sku, quantity: Math.max(1, Math.floor(qty.value) || 1) })
    added.value = true
    if (addedTimer) clearTimeout(addedTimer)
    addedTimer = setTimeout(() => {
      added.value = false
    }, 1500)
  } catch (e) {
    addError.value = getErrorMessage(e, 'Не удалось добавить в корзину')
  } finally {
    adding.value = false
  }
}

onMounted(load)

onUnmounted(() => {
  if (addedTimer) clearTimeout(addedTimer)
})

const STOCK_META: Record<string, { label: string; cls: string }> = {
  IN_STOCK: { label: 'В наличии', cls: 'badge-success' },
  PREORDER: { label: 'Под заказ', cls: 'badge-warning' },
  ARCHIVED: { label: 'Архив', cls: 'badge-danger' },
}
</script>

<template>
  <div>
    <button class="btn-ghost -ml-2 mb-2 py-2" @click="router.back()">
      <Icon name="heroicons:chevron-left" class="w-5 h-5" /> Назад
    </button>

    <!-- Skeleton -->
    <div v-if="loading" class="card p-4">
      <div class="skeleton aspect-square mb-4 rounded-card" />
      <div class="skeleton h-5 w-1/3 mb-2" />
      <div class="skeleton h-7 w-3/4 mb-4" />
      <div class="skeleton h-10 w-full" />
    </div>

    <!-- Не найдено -->
    <div v-else-if="notFound" class="card p-8 text-center">
      <Icon name="heroicons:archive-box-x-mark" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
      <p class="text-ink-muted mb-4 text-sm">Товар не найден</p>
      <NuxtLink to="/m/catalog" class="btn-primary">В каталог</NuxtLink>
    </div>

    <!-- Ошибка -->
    <div v-else-if="error" class="card p-6 text-center">
      <div class="badge-danger mb-3 inline-flex">{{ error }}</div>
      <div><button class="btn-primary" @click="load">Повторить</button></div>
    </div>

    <!-- Карточка -->
    <div v-else-if="product">
      <div class="card aspect-square overflow-hidden bg-surface-2 flex items-center justify-center mb-4">
        <img v-if="photoOf(product)" :src="photoOf(product)!" :alt="product.name" class="w-full h-full object-cover">
        <Icon v-else name="heroicons:photo" class="w-16 h-16 text-ink-faint" />
      </div>

      <div class="flex flex-wrap items-center gap-2 mb-2">
        <span v-if="product.brand" class="badge-info">{{ product.brand.name }}</span>
        <span :class="STOCK_META[product.stock_status]?.cls || 'badge-info'">{{ STOCK_META[product.stock_status]?.label || product.stock_status }}</span>
      </div>

      <h1 class="text-lg font-bold leading-snug mb-1">{{ product.name }}</h1>
      <p class="text-xs text-ink-faint mb-4"> Артикул: {{ product.sku }}<span v-if="product.series"> · {{ product.series.name }}</span></p>

      <div class="card p-4 mb-4">
        <div class="flex items-baseline gap-2 flex-wrap">
          <span class="text-2xl font-bold text-primary">{{ formatMoney(product.has_discount ? product.client_price : product.retail_price, product.currency) }}</span>
          <span v-if="product.has_discount" class="text-sm text-ink-faint line-through">{{ formatMoney(product.retail_price, product.currency) }}</span>
        </div>
        <p v-if="product.has_discount" class="text-xs text-ink-muted mt-1.5">Ваша цена со скидкой</p>
      </div>

      <div class="flex items-center gap-2">
        <input v-model="qty" type="number" min="1" class="input py-3 w-20 text-center">
        <button class="btn-primary flex-1 justify-center py-3" :disabled="adding" @click="addToCart">
          <span v-if="adding" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <Icon v-else-if="added" name="heroicons:check" class="w-4 h-4" />
          <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
          {{ added ? 'Добавлено' : 'В корзину' }}
        </button>
      </div>
      <div v-if="addError" class="badge-danger w-full justify-center py-2.5 mt-3">{{ addError }}</div>

      <NuxtLink to="/m/cart" class="btn-ghost w-full justify-center py-2.5 mt-2">Перейти в корзину</NuxtLink>
    </div>
  </div>
</template>
