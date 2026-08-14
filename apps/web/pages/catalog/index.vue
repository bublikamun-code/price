<script setup lang="ts">
// Каталог / Прайс-лист — ключевая страница (SITEMAP.md §6).
// Реальные данные: GET /api/v1/catalog/products, /catalog/filters.
import type { CatalogPage, FiltersOut, ProductCard } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Каталог' })

const { request } = useApi()
const route = useRoute()

type Sort = 'name' | '-name' | 'price' | '-price' | 'sku'
const PER_PAGE = 12

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
const selectedStock = ref<string>('') // '' | IN_STOCK | PREORDER
const sort = ref<Sort>('name')
const page = ref(1)
const priceMode = ref<'discount' | 'retail'>('discount')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

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

// мини-помощники для карточки
const { photoOf } = useProductPhoto()
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
      <div class="flex items-center gap-2">
        <!-- Переключатель цены -->
        <div class="flex bg-surface border border-border rounded-pill p-1">
          <button
            class="px-3 py-1.5 rounded-pill text-sm font-medium transition-colors"
            :class="priceMode === 'discount' ? 'bg-primary text-white' : 'text-ink-muted'"
            @click="priceMode = 'discount'"
          >Со скидкой</button>
          <button
            class="px-3 py-1.5 rounded-pill text-sm font-medium transition-colors"
            :class="priceMode === 'retail' ? 'bg-primary text-white' : 'text-ink-muted'"
            @click="priceMode = 'retail'"
          >Розница</button>
        </div>
        <!-- Сортировка -->
        <select v-model="sort" class="input py-2" @change="applyFilters">
          <option value="name">Название А→Я</option>
          <option value="-name">Название Я→А</option>
          <option value="price">Цена ↑</option>
          <option value="-price">Цена ↓</option>
          <option value="sku">Артикул</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="badge-danger w-full justify-center py-3 mb-6">{{ error }}</div>

    <div class="flex gap-6">
      <!-- Фильтры -->
      <aside class="hidden lg:block w-64 shrink-0">
        <div class="card p-5 sticky top-[88px]">
          <h3 class="font-semibold mb-4">Фильтры</h3>

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
            <label v-for="b in filters.brands" :key="b.id" class="flex items-center gap-2 text-sm py-1 cursor-pointer">
              <input v-model="selectedBrands" type="checkbox" :value="b.id" class="rounded border-border" @change="applyFilters" >
              {{ b.name }}
            </label>
          </div>

          <div v-if="filters.series.length" class="mb-5">
            <label class="label">Серия</label>
            <label v-for="s in filters.series" :key="s.id" class="flex items-center gap-2 text-sm py-1 cursor-pointer">
              <input v-model="selectedSeries" type="checkbox" :value="s.id" class="rounded border-border" @change="applyFilters" >
              {{ s.name }}
            </label>
          </div>

          <div class="mb-5">
            <label class="label">Наличие</label>
            <select v-model="selectedStock" class="input py-2" @change="applyFilters">
              <option value="">Любое</option>
              <option value="IN_STOCK">В наличии</option>
              <option value="PREORDER">Под заказ</option>
            </select>
          </div>

          <button class="btn-ghost w-full justify-center" @click="resetFilters">Сбросить</button>
        </div>
      </aside>

      <!-- Сетка -->
      <div class="flex-1 min-w-0">
        <!-- Skeletons -->
        <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
          <div v-for="i in 6" :key="i" class="card p-5">
            <div class="skeleton aspect-square mb-4 rounded-card"/>
            <div class="skeleton h-4 w-1/3 mb-3"/>
            <div class="skeleton h-5 w-3/4 mb-2"/>
            <div class="skeleton h-4 w-1/2 mb-4"/>
            <div class="skeleton h-9 w-full"/>
          </div>
        </div>

        <!-- Пусто -->
        <div v-else-if="!products.length" class="card p-12 text-center text-ink-muted">
          <Icon name="heroicons:archive-box-x-mark" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
          <p>Ничего не найдено. Измените условия поиска или сбросьте фильтры.</p>
        </div>

        <!-- Карточки -->
        <div v-else class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
          <article v-for="p in products" :key="p.id" class="card card-hover p-5 flex flex-col">
            <!-- Фото -->
            <div class="aspect-square bg-canvas rounded-card mb-4 flex items-center justify-center overflow-hidden">
              <img
                v-if="photoOf(p)"
                :src="photoOf(p)!"
                :alt="p.name"
                loading="lazy"
                class="w-full h-full object-contain"
              >
              <Icon v-else name="heroicons:photo" class="w-10 h-10 text-ink-faint" />
            </div>

            <div class="flex items-start justify-between gap-2 mb-1">
              <span v-if="p.brand" class="badge-info">{{ p.brand.name }}</span>
              <span :class="p.stock_status === 'IN_STOCK' ? 'badge-success' : 'badge-warning'">
                {{ stockLabel[p.stock_status] || p.stock_status }}
              </span>
            </div>
            <NuxtLink :to="`/catalog/${p.sku}`" class="block font-semibold text-base mb-1 line-clamp-2 hover:text-primary transition-colors">
              {{ p.name }}
            </NuxtLink>
            <p class="text-xs text-ink-faint mb-3">Артикул: {{ p.sku }}<span v-if="p.series"> · {{ p.series.name }}</span></p>

            <!-- Характеристики -->
            <div v-if="attrChips(p).length" class="flex flex-wrap gap-1.5 mb-3">
              <span v-for="c in attrChips(p)" :key="c.label" class="chip">
                {{ c.label }}: <span class="font-medium">{{ c.value }}</span>
              </span>
            </div>

            <div class="mt-auto">
              <div v-if="priceMode === 'discount' && p.has_discount" class="flex items-baseline gap-2 mb-3">
                <span class="text-xl font-bold text-primary">{{ p.client_price }} {{ p.currency }}</span>
                <span class="text-sm text-ink-faint line-through">{{ p.retail_price }} {{ p.currency }}</span>
              </div>
              <div v-else class="mb-3">
                <span class="text-xl font-bold">{{ p.retail_price }} {{ p.currency }}</span>
              </div>
              <div class="flex items-center gap-2">
                <input
                  type="number"
                  min="1"
                  :value="getQty(p.sku)"
                  class="input py-2 w-20 text-center"
                  @input="setQty(p.sku, +($event.target as HTMLInputElement).value)"
                >
                <button
                  class="btn-primary flex-1 py-2"
                  :disabled="addingSku === p.sku"
                  @click="addToCart(p)"
                >
                  <span v-if="addingSku === p.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
                  <Icon v-else-if="addedSku === p.sku" name="heroicons:check" class="w-4 h-4" />
                  <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" />
                  {{ addedSku === p.sku ? 'Добавлено' : 'В корзину' }}
                </button>
              </div>
            </div>
          </article>
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
