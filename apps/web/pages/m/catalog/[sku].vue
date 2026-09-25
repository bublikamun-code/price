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

const catalogMeta = computed(() => {
  const value = product.value
  if (!value) return ''
  return [value.brand?.name, value.series?.name].filter(Boolean).join(' · ') || 'Без бренда и серии'
})

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

const STOCK_META: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  IN_STOCK: { label: 'В наличии', tone: 'success' },
  PREORDER: { label: 'Под заказ', tone: 'warning' },
  ARCHIVED: { label: 'Архив', tone: 'danger' },
}
</script>

<template>
  <div>
    <button type="button" class="btn-ghost -ml-2 mb-3 min-h-11" @click="router.back()">
      <Icon name="heroicons:chevron-left" class="size-5" aria-hidden="true" /> Назад
    </button>

    <div v-if="loading" class="border border-border bg-surface" aria-label="Загрузка товара" aria-busy="true">
      <div class="grid grid-cols-[96px_1fr] gap-4 p-4"><div class="skeleton size-24" /><div><div class="skeleton h-5 w-3/4" /><div class="skeleton mt-3 h-4 w-1/2" /><div class="skeleton mt-5 h-8 w-1/3" /></div></div>
    </div>
    <div v-else-if="notFound" class="border border-border bg-surface p-5">
      <p class="text-sm font-semibold text-ink">Товар не найден</p>
      <p class="mt-1 text-sm text-ink-muted">Позиция исключена из каталога или ссылка устарела.</p>
      <NuxtLink to="/m/catalog" class="btn-primary mt-4 inline-flex min-h-11 items-center">В каталог</NuxtLink>
    </div>
    <div v-else-if="error" class="border border-danger/50 bg-danger-soft p-5" role="alert">
      <p class="text-sm font-semibold text-ink">Не удалось загрузить товар</p>
      <p class="mt-1 text-sm text-ink-muted">{{ error }}</p>
      <button type="button" class="btn-outline mt-4 min-h-11" @click="load">Повторить</button>
    </div>

    <article v-else-if="product" class="border border-border bg-surface">
      <header class="grid grid-cols-[96px_minmax(0,1fr)] gap-4 border-b border-border p-4 sm:grid-cols-[160px_minmax(0,1fr)] sm:p-5">
        <div class="flex size-24 items-center justify-center overflow-hidden border border-border bg-background sm:size-40">
          <img v-if="photoOf(product)" :src="photoOf(product)!" :alt="product.name" class="size-full object-contain">
          <Icon v-else name="heroicons:photo" class="size-10 text-ink-faint" aria-hidden="true" />
        </div>
        <div class="min-w-0 self-center">
          <PageHeading
            class="mb-0"
            :eyebrow="product.sku"
            :title="product.name"
            :description="catalogMeta"
          >
            <template #actions>
              <UiStatusBadge :tone="STOCK_META[product.stock_status]?.tone || 'info'" :label="STOCK_META[product.stock_status]?.label || product.stock_status" dot />
            </template>
          </PageHeading>
        </div>
      </header>

      <div class="grid sm:grid-cols-[minmax(0,1fr)_18rem]">
        <section class="border-b border-border p-4 sm:border-b-0 sm:border-r">
          <p class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Клиентская цена</p>
          <p class="numeric mt-2 text-2xl font-bold text-action">{{ formatMoney(product.has_discount ? product.client_price : product.retail_price, product.currency) }}</p>
          <p v-if="product.has_discount" class="numeric mt-1 text-sm text-ink-muted line-through">{{ formatMoney(product.retail_price, product.currency) }}</p>
          <p v-if="product.has_discount" class="mt-2 text-xs text-success">Цена с индивидуальной скидкой</p>
        </section>
        <section class="p-4">
          <label class="text-xs font-semibold uppercase tracking-wide text-ink-muted" for="m_product_qty">Количество</label>
          <input id="m_product_qty" v-model="qty" type="number" min="1" inputmode="numeric" :aria-label="`Количество товара «${product.name}»`" class="input numeric mt-2 min-h-11 text-center">
          <button type="button" class="btn-primary mt-2 min-h-11 w-full justify-center" :disabled="adding" @click="addToCart">
            <span v-if="adding" class="size-4 animate-spin border-2 border-white/40 border-t-white" />
            <Icon v-else-if="added" name="heroicons:check" class="size-4" />
            <Icon v-else name="heroicons:shopping-cart" class="size-4" />
            {{ added ? 'Добавлено' : 'В корзину' }}
          </button>
        </section>
      </div>
      <div v-if="addError" class="border-t border-danger/50 bg-danger-soft p-3 text-sm text-ink" role="alert">{{ addError }}</div>
    </article>

    <NuxtLink to="/m/cart" class="btn-ghost mt-3 min-h-11 w-full justify-center">Перейти в корзину</NuxtLink>
  </div>
</template>
