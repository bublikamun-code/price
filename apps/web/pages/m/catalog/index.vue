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
// Справочник брендов не зависит от поиска/страницы, поэтому загружаем его
// только при первом открытии мобильного каталога.
let brandsLoaded = false
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
    const catalogPromise = request<CatalogPage>('/api/v1/catalog/products', { query: queryParams(page.value) })
    const filtersPromise = brandsLoaded
      ? Promise.resolve(null)
      : request<FiltersOut>('/api/v1/catalog/filters')
    const [catalog, f] = await Promise.all([catalogPromise, filtersPromise])
    products.value = catalog.data
    total.value = catalog.meta.total
    if (f) {
      brands.value = f.brands
      brandsLoaded = true
    }
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

function resetFilters() {
  q.value = ''
  brandId.value = ''
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
    <PageHeading
      eyebrow="Каталог v1"
      title="Товары"
      :description="`Найдено: ${total}`"
    />

    <form class="mb-4 border border-border bg-surface p-3" @submit.prevent="search">
      <label class="sr-only" for="m_catalog_search">Поиск по каталогу</label>
      <div class="relative">
        <Icon name="heroicons:magnifying-glass" class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
        <input id="m_catalog_search" v-model="q" class="input min-h-11 pl-9" type="search" placeholder="Артикул или наименование">
      </div>
      <label class="sr-only" for="m_catalog_brand">Производитель</label>
      <select id="m_catalog_brand" v-model="brandId" class="input mt-2 min-h-11" @change="search">
        <option value="">Все производители</option>
        <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
      </select>
      <button type="submit" class="btn-primary mt-2 min-h-11 w-full justify-center" :disabled="loading">Найти</button>
    </form>

    <div v-if="error" class="mb-4 flex items-center gap-3 border border-danger/50 bg-danger-soft p-3" role="alert">
      <p class="min-w-0 flex-1 text-sm text-ink">{{ error }}</p>
      <button type="button" class="btn-outline min-h-11 shrink-0" @click="load">Повторить</button>
    </div>

    <div v-if="loading && !products.length" class="border border-border bg-surface" aria-label="Загрузка каталога" aria-busy="true">
      <div v-for="i in 6" :key="i" class="flex h-24 items-center gap-3 border-b border-border p-3 last:border-b-0">
        <div class="skeleton size-14 shrink-0" />
        <div class="flex-1"><div class="skeleton h-4 w-3/4" /><div class="skeleton mt-2 h-3 w-1/2" /></div>
      </div>
    </div>

    <div v-else-if="!products.length" class="border border-border bg-surface p-5">
      <p class="text-sm font-semibold text-ink">Товары не найдены</p>
      <p class="mt-1 text-sm text-ink-muted">Измените запрос или сбросьте фильтры.</p>
      <button type="button" class="btn-outline mt-4 min-h-11" @click="resetFilters">Сбросить фильтры</button>
    </div>

    <section v-else class="border border-border bg-surface" aria-label="Список товаров">
      <header class="flex min-h-11 items-center justify-between border-b border-border bg-surface-2 px-3 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        <span>Запись товара</span><span class="numeric">{{ products.length }} / {{ total }}</span>
      </header>
      <div class="divide-y divide-border">
        <NuxtLink
          v-for="p in products"
          :key="p.id"
          :to="`/m/catalog/${encodeURIComponent(p.sku)}`"
          class="grid min-h-24 grid-cols-[56px_minmax(0,1fr)] gap-3 p-3 hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-action sm:grid-cols-[64px_minmax(0,1fr)_auto]"
        >
          <div class="flex size-14 items-center justify-center overflow-hidden border border-border bg-background sm:size-16">
            <img v-if="thumbOf(p.photo_key)" :src="thumbOf(p.photo_key)!" :alt="p.name" loading="lazy" class="size-full object-contain">
            <Icon v-else name="heroicons:photo" class="size-6 text-ink-faint" aria-hidden="true" />
          </div>
          <div class="min-w-0">
            <p v-if="p.brand" class="truncate text-xs font-semibold text-ink-muted">{{ p.brand.name }}</p>
            <p class="mt-0.5 line-clamp-2 text-sm font-semibold leading-5 text-ink">{{ p.name }}</p>
            <p class="numeric mt-1 truncate text-xs text-ink-muted">SKU {{ p.sku }}</p>
            <span :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'" class="mt-2">{{ stockLabel[p.stock_status] || p.stock_status }}</span>
          </div>
          <div class="col-start-2 flex items-end justify-between border-t border-border pt-2 sm:col-start-auto sm:flex-col sm:items-end sm:border-t-0 sm:pt-0">
            <span v-if="p.has_discount" class="numeric text-xs text-ink-muted line-through">{{ formatMoney(p.retail_price, p.currency) }}</span>
            <span class="numeric text-base font-bold text-action">{{ formatMoney(priceOf(p), p.currency) }}</span>
          </div>
        </NuxtLink>
      </div>
    </section>

    <button v-if="hasMore && !loading" type="button" class="btn-outline mt-3 min-h-11 w-full justify-center" :disabled="loadingMore" @click="loadMore">
      {{ loadingMore ? 'Загрузка…' : 'Показать ещё' }}
    </button>
    <p v-if="!loading && products.length" class="mt-3 text-xs text-ink-muted">Показано {{ products.length }} из {{ total }}</p>
  </div>
</template>
