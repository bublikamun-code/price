<script setup lang="ts">
// Мобильный каталог (Mini App): поиск + фильтр по производителю, плитка 2 колонки.
import type { CatalogPage, FiltersOut, ProductCard } from '~/types/api'

definePageMeta({ layout: 'miniapp', middleware: 'm-auth' })
useHead({ title: 'Каталог' })
const { request } = useApi()
const { thumbOf } = useProductPhoto()

const PER_PAGE = 12

const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const products = ref<ProductCard[]>([])
const brands = ref<FiltersOut['brands']>([])
const total = ref(0)
const q = ref('')
const brandId = ref('')
const page = ref(1)
const hasMore = computed(() => products.value.length < total.value)
const stockLabel: Record<string, string> = { IN_STOCK: 'В наличии', PREORDER: 'Под заказ' }
function priceOf(p: ProductCard) {
  return p.has_discount ? p.client_price : p.retail_price
}

function queryParams(pageNo: number) {
  return {
    q: q.value || undefined,
    brand: brandId.value || undefined,
    page: pageNo,
    per_page: PER_PAGE,
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [catalog, f] = await Promise.all([
      request<CatalogPage>('/api/v1/catalog/products', { query: queryParams(page.value) }),
      request<FiltersOut>('/api/v1/catalog/filters'),
    ])
    products.value = catalog.data
    total.value = catalog.meta.total
    brands.value = f.brands
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить каталог')
  } finally {
    loading.value = false
  }
}

// Поиск/смена бренда: всегда с первой страницы.
function search() {
  if (loading.value) return
  page.value = 1
  load()
}

async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  error.value = ''
  try {
    const catalog = await request<CatalogPage>('/api/v1/catalog/products', {
      query: queryParams(page.value + 1),
    })
    products.value = [...products.value, ...catalog.data]
    total.value = catalog.meta.total
    page.value = catalog.meta.page
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить товары')
  } finally {
    loadingMore.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-lg font-bold mb-3">Каталог</h1>

    <form class="flex flex-col gap-2 mb-4" @submit.prevent="search">
      <div class="relative">
        <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
        <input v-model="q" class="input pl-10" type="search" placeholder="Артикул, наименование">
      </div>
      <select v-model="brandId" class="input py-2.5" @change="search">
        <option value="">Все производители</option>
        <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
      </select>
    </form>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <!-- Skeletons -->
    <div v-if="loading && !products.length" class="grid grid-cols-2 gap-3">
      <div v-for="i in 6" :key="i" class="card p-3">
        <div class="skeleton aspect-square mb-3 rounded-card" />
        <div class="skeleton h-4 w-3/4 mb-2" />
        <div class="skeleton h-5 w-1/2" />
      </div>
    </div>

    <!-- Пусто -->
    <div v-else-if="!products.length" class="card p-8 text-center text-ink-muted">
      <Icon name="heroicons:archive-box-x-mark" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
      <p class="text-sm">Ничего не найдено</p>
    </div>

    <!-- Плитка -->
    <div v-else class="grid grid-cols-2 gap-3">
      <NuxtLink
        v-for="p in products"
        :key="p.id"
        :to="`/m/catalog/${encodeURIComponent(p.sku)}`"
        class="card card-hover p-3 flex flex-col"
      >
        <div class="aspect-square bg-canvas rounded-card mb-2.5 flex items-center justify-center overflow-hidden">
          <img
            v-if="thumbOf(p.photo_key)"
            :src="thumbOf(p.photo_key)!"
            :alt="p.name"
            loading="lazy"
            class="w-full h-full object-contain"
          >
          <Icon v-else name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
        </div>
        <span v-if="p.brand" class="chip bg-canvas text-ink-muted self-start mb-1.5 !px-2 !py-0.5">{{ p.brand.name }}</span>
        <span class="text-sm font-medium leading-snug line-clamp-2 mb-2">{{ p.name }}</span>
        <div class="mt-auto">
          <div class="flex items-baseline gap-1.5 flex-wrap mb-1">
            <span class="text-base font-bold" :class="p.has_discount ? 'text-primary' : 'text-ink'">{{ formatMoney(priceOf(p), p.currency) }}</span>
            <span v-if="p.has_discount" class="text-xs text-ink-faint line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
          </div>
          <span :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'">{{ stockLabel[p.stock_status] || p.stock_status }}</span>
        </div>
      </NuxtLink>
    </div>

    <button
      v-if="hasMore && !loading"
      class="btn-outline w-full justify-center py-3 mt-4"
      :disabled="loadingMore"
      @click="loadMore"
    >
      <span v-if="loadingMore" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin" />
      {{ loadingMore ? 'Загрузка…' : 'Ещё' }}
    </button>

    <p v-if="!loading && products.length" class="text-xs text-ink-faint text-center mt-3"> Показано {{ products.length }} из {{ total }}</p>
  </div>
</template>
