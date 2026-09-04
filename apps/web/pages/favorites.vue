<script setup lang="ts">
// Избранное клиента. См. SITEMAP.md §6, §16.1 (фича A).
import type { FavoriteListPage, FavoriteRead } from '~/types/api'

definePageMeta({ layout: 'client', middleware: 'auth' })
useHead({ title: 'Избранное' })

const { request } = useApi()
const { thumbOf } = useProductPhoto()
const cart = useCart()
// Общее состояние избранного (каталог/карточка товара) — удаляем через него,
// чтобы сердечки в каталоге не расходились со списком.
const favs = useFavorites()
const PER_PAGE = 12
const loading = ref(true)
const error = ref('')
const favorites = ref<FavoriteRead[]>([])
const total = ref(0)
const page = ref(1)
const removingSku = ref<string | null>(null)
const addingSku = ref<string | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<FavoriteListPage>('/api/v1/favorites', {
      query: { page: page.value, per_page: PER_PAGE },
    })
    favorites.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить избранное')
  } finally {
    loading.value = false
  }
}

async function removeFav(f: FavoriteRead) {
  removingSku.value = f.sku
  error.value = ''
  try {
    await favs.remove(f.sku)
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось удалить из избранного')
  } finally {
    removingSku.value = null
  }
}

async function addToCart(f: FavoriteRead) {
  if (addingSku.value) return
  addingSku.value = f.sku
  error.value = ''
  try {
    await cart.add({ sku: f.sku, quantity: 1 })
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось добавить в корзину')
  } finally {
    addingSku.value = null
  }
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Избранное</h1>
      <p class="text-sm text-ink-muted mt-1">
        <template v-if="!loading">{{ total }} товаров</template>
        <template v-else>Загрузка…</template>
      </p>
    </div>

    <div v-if="error" class="badge-danger w-full justify-center py-3 mb-6">{{ error }}</div>

    <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
      <div v-for="i in 3" :key="i" class="card p-5">
        <div class="skeleton aspect-square mb-4 rounded-card"/>
        <div class="skeleton h-4 w-3/4 mb-2"/>
        <div class="skeleton h-9 w-full"/>
      </div>
    </div>

    <div v-else-if="!favorites.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:heart" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="mb-4">В избранном пока пусто</p>
      <NuxtLink to="/catalog" class="btn-primary">Найти товары</NuxtLink>
    </div>

    <div v-else>
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
        <article v-for="f in favorites" :key="f.product_id" class="card card-hover p-5 flex flex-col">
          <div class="aspect-square bg-canvas rounded-card mb-4 flex items-center justify-center overflow-hidden">
            <img v-if="thumbOf(f.photo_key)" :src="thumbOf(f.photo_key)!" :alt="f.name" loading="lazy" class="w-full h-full object-contain" >
            <Icon v-else name="heroicons:photo" class="w-10 h-10 text-ink-faint" />
          </div>

          <div class="flex items-start justify-between gap-2 mb-1">
            <span v-if="f.brand_name" class="badge-info">{{ f.brand_name }}</span>
            <button
              class="btn-ghost p-1.5 text-danger shrink-0"
              :disabled="removingSku === f.sku"
              title="Убрать из избранного"
              @click="removeFav(f)"
            >
              <span v-if="removingSku === f.sku" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
              <Icon v-else name="heroicons:heart-solid" class="w-4 h-4" />
            </button>
          </div>

          <NuxtLink :to="`/catalog/${f.sku}`" class="font-semibold text-base mb-1 line-clamp-2 hover:text-primary">
            {{ f.name }}
          </NuxtLink>
          <p class="text-xs text-ink-faint mb-3">Артикул: {{ f.sku }}</p>

          <div class="mt-auto">
            <div v-if="f.has_discount" class="flex items-baseline gap-2 mb-3">
              <span class="text-xl font-bold text-primary">{{ f.client_price }} {{ f.currency }}</span>
              <span class="text-sm text-ink-faint line-through">{{ f.retail_price }} {{ f.currency }}</span>
            </div>
            <div v-else class="mb-3">
              <span class="text-xl font-bold">{{ f.retail_price }} {{ f.currency }}</span>
            </div>
            <button
              class="btn-primary w-full py-2"
              :disabled="addingSku === f.sku"
              @click="addToCart(f)"
            >
              <span v-if="addingSku === f.sku" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
              <Icon v-else name="heroicons:shopping-cart" class="w-4 h-4" /> В корзину
            </button>
          </div>
        </article>
      </div>

      <nav v-if="totalPages > 1" class="flex items-center justify-center gap-1 mt-8">
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
</template>
