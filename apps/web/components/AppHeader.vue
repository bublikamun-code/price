<script setup lang="ts">
// Глобальная шапка. Состав зависит от роли — см. SITEMAP.md §2.
import type { AuthUser } from '~/composables/useAuth'
import type { CatalogPage } from '~/types/api'

const auth = useAuth()
const { count: cartCount, refresh: refreshCart } = useCart()
const { unreadCount, refresh: refreshNotifications, startStream, stopStream } = useNotifications()

// Поиск на мобильных (<md): раскрывающееся поле справа (как было).
const searchOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)

function openSearch() {
  searchOpen.value = true
  nextTick(() => searchInput.value?.focus())
}
function closeSearch() {
  searchOpen.value = false
  searchQuery.value = ''
}
function toggleSearch() {
  if (searchOpen.value) closeSearch()
  else openSearch()
}
function closeSearchIfEmpty() {
  if (!searchQuery.value.trim()) closeSearch()
}
function onSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  navigateTo({ path: '/catalog', query: { q } })
  closeSearch()
}

// Мгновенный поиск (typeahead) — только десктоп ≥md (§16 п.30).
// GET /api/v1/catalog/products?q=…&page=1&per_page=6 — те же параметры,
// что использует pages/catalog/index.vue (там per_page, не page_size).
interface TypeaheadProduct {
  id: string
  sku: string
  name: string
  photo_key: string | null
  attributes?: Record<string, unknown>
  base_price_byn: number
  retail_price: number
  client_price: number
  currency: string
  has_discount: boolean
}

const TA_MIN_LEN = 2
const TA_DEBOUNCE_MS = 250

const taQuery = ref('')
const taResults = ref<TypeaheadProduct[]>([])
const taLoading = ref(false)
const taOpen = ref(false)
const taActive = ref(-1)
const taWrap = ref<HTMLDivElement | null>(null)
let taTimer: ReturnType<typeof setTimeout> | null = null
let taSeq = 0

const { photoOf } = useProductPhoto()
const { request } = useApi()

function taDisplayPrice(p: TypeaheadProduct): number {
  return p.has_discount ? p.client_price : p.retail_price
}

async function taFetch() {
  const q = taQuery.value.trim()
  if (q.length < TA_MIN_LEN) {
    taClose()
    return
  }
  const seq = ++taSeq
  taLoading.value = true
  taOpen.value = true
  try {
    const res = await request<CatalogPage>('/api/v1/catalog/products', {
      query: { q, page: 1, per_page: 6 },
    })
    // устаревший ответ более раннего запроса — игнорируем
    if (seq !== taSeq) return
    taResults.value = res.data as unknown as TypeaheadProduct[]
    taActive.value = -1
    taOpen.value = true
  } catch {
    // ошибки API (в т.ч. гость без прав) — молча закрываем дропдаун
    if (seq === taSeq) taClose()
  } finally {
    if (seq === taSeq) taLoading.value = false
  }
}

function taOnInput() {
  if (taTimer) clearTimeout(taTimer)
  const q = taQuery.value.trim()
  if (q.length < TA_MIN_LEN) {
    taClose()
    return
  }
  taTimer = setTimeout(taFetch, TA_DEBOUNCE_MS)
}

function taClose() {
  taOpen.value = false
  taActive.value = -1
  taLoading.value = false
}

function taClear() {
  taQuery.value = ''
  taResults.value = []
  taClose()
}

function taGoProduct(p: TypeaheadProduct) {
  taClear()
  navigateTo(`/catalog/${p.sku}`)
}

function taGoCatalog() {
  const q = taQuery.value.trim()
  taClear()
  navigateTo({ path: '/catalog', query: q ? { q } : {} })
}

function taOnKeydown(e: KeyboardEvent) {
  if (!taOpen.value || !taResults.value.length) {
    if (e.key === 'Enter') taGoCatalog()
    if (e.key === 'Escape') taClear()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    taActive.value = (taActive.value + 1) % taResults.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    taActive.value = taActive.value <= 0 ? taResults.value.length - 1 : taActive.value - 1
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const p = taResults.value[taActive.value]
    if (p) taGoProduct(p)
    else taGoCatalog()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    taClose()
  }
}

function taOnDocClick(e: MouseEvent) {
  if (taWrap.value && !taWrap.value.contains(e.target as Node)) taClose()
}

onMounted(() => document.addEventListener('click', taOnDocClick))
onBeforeUnmount(() => document.removeEventListener('click', taOnDocClick))

onMounted(() => {
  // Fallback: если при смене layout/store состояние не подхватилось,
  // восстанавливаем его из cookie напрямую (§11, плагин auth.session.ts).
  if (!auth.isAuthenticated) {
    const tokenC = useCookie<string | null>('auth_token')
    const userC = useCookie<AuthUser | null>('auth_user')
    if (tokenC.value && userC.value) {
      auth.token = tokenC.value
      auth.user = userC.value
      auth.fetchMe().catch(() => {})
    }
  }

  if (auth.isClient) refreshCart()
  if (auth.isAuthenticated) {
    refreshNotifications()
    startStream() // SSE-бейдж (§16 п.26); при фатальной ошибке композабл сам уйдёт в poll-fallback
  }
})

onUnmounted(() => stopStream())
</script>

<template>
  <header class="sticky top-0 z-40 h-18 border-b border-border bg-surface/90 backdrop-blur-md shadow-sm">
    <div class="container-app h-full flex items-center gap-2 py-3">
      <!-- Logo -->
      <NuxtLink to="/" class="flex items-center gap-2 shrink-0">
        <span class="font-display text-xl font-bold">
          <span class="text-primary">Price</span><span class="text-ink">Portal</span>
        </span>
      </NuxtLink>

      <div class="flex-1"/>

      <!-- Правая часть -->
      <nav class="flex items-center gap-1 sm:gap-2">
        <template v-if="auth.isAuthenticated">
          <!-- Валюта (клиент): display-валюта из профиля; клик → настройки валюты -->
          <button
            class="btn-ghost px-3 hidden sm:inline-flex"
            title="Валюта отображения — меняется в профиле"
            @click="navigateTo('/profile')"
          >
            <span class="badge-info">{{ auth.user?.displayCurrency ?? 'BYN' }}</span>
          </button>

          <!-- Уведомления -->
          <button class="btn-ghost p-2.5 relative" title="Уведомления" @click="navigateTo('/notifications')">
            <Icon name="heroicons:bell" class="w-5 h-5" />
            <span v-if="unreadCount" class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-danger text-white text-[10px] font-semibold rounded-pill flex items-center justify-center">
              {{ unreadCount > 99 ? '99+' : unreadCount }}
            </span>
          </button>

          <!-- Корзина (клиент) -->
          <NuxtLink v-if="auth.isClient" to="/cart" class="btn-ghost p-2.5 relative" title="Корзина">
            <Icon name="heroicons:shopping-cart" class="w-5 h-5" />
            <span v-if="cartCount" class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-primary text-white text-[10px] font-semibold rounded-pill flex items-center justify-center">
              {{ cartCount }}
            </span>
          </NuxtLink>

          <!-- Поиск (десктоп ≥md): инлайн typeahead с дропдауном -->
          <div ref="taWrap" class="relative hidden md:block">
            <div class="relative">
              <Icon name="heroicons:magnifying-glass" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none" />
              <input
                v-model="taQuery"
                type="search"
                role="combobox"
                aria-expanded="false"
                aria-haspopup="listbox"
                placeholder="Поиск по каталогу..."
                class="input w-64 xl:w-80 h-9 py-2 pl-9"
                :class="{ 'opacity-60': taLoading }"
                @input="taOnInput"
                @keydown="taOnKeydown"
              >
            </div>
            <!-- Дропдаун результатов -->
            <div
              v-if="taOpen"
              class="absolute right-0 top-full mt-2 w-80 xl:w-[26rem] card p-1 z-50 max-h-96 overflow-y-auto shadow-card"
              role="listbox"
            >
              <template v-if="taResults.length">
                <button
                  v-for="(p, i) in taResults"
                  :key="p.id"
                  class="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors"
                  :class="i === taActive ? 'bg-secondary-soft' : 'hover:bg-canvas'"
                  role="option"
                  :aria-selected="i === taActive"
                  @mousedown.prevent="taGoProduct(p)"
                  @mousemove="taActive = i"
                >
                  <img
                    v-if="photoOf(p)"
                    :src="photoOf(p)!"
                    :alt="p.name"
                    class="w-10 h-10 rounded object-cover shrink-0 bg-canvas"
                  >
                  <span
                    v-else
                    class="w-10 h-10 rounded bg-canvas text-ink-faint flex items-center justify-center shrink-0"
                  >
                    <Icon name="heroicons:photo" class="w-5 h-5" />
                  </span>
                  <span class="min-w-0 flex-1">
                    <span class="block text-sm font-medium text-ink truncate">{{ p.name }}</span>
                    <span class="block text-xs text-ink-faint truncate">{{ p.sku }}</span>
                  </span>
                  <span class="text-sm font-semibold text-ink shrink-0">
                    {{ formatMoney(taDisplayPrice(p), p.currency) }}
                  </span>
                </button>
              </template>
              <p v-else-if="!taLoading" class="px-3 py-4 text-sm text-ink-faint text-center">
                Ничего не найдено
              </p>
              <p v-else class="px-3 py-4 text-sm text-ink-faint text-center opacity-60">
                Загрузка...
              </p>
            </div>
          </div>

          <!-- Поиск (мобильные <md): как было — раскрывающееся поле -->
          <div class="flex items-center md:hidden">
            <input
              v-if="searchOpen"
              ref="searchInput"
              v-model="searchQuery"
              type="search"
              placeholder="Поиск по каталогу..."
              class="input w-40 sm:w-56 h-10"
              @keyup.enter="onSearch"
              @blur="closeSearchIfEmpty"
            >
            <button
              class="btn-ghost p-2.5 shrink-0"
              :title="searchOpen ? 'Закрыть поиск' : 'Поиск по каталогу'"
              @click="toggleSearch"
            >
              <Icon :name="searchOpen ? 'heroicons:x-mark' : 'heroicons:magnifying-glass'" class="w-5 h-5" />
            </button>
          </div>

          <!-- Профиль -->
          <div class="relative group">
            <button class="flex items-center gap-2 px-2 py-1.5 rounded-pill hover:bg-canvas transition-colors">
              <span class="w-8 h-8 rounded-pill bg-secondary-soft text-secondary flex items-center justify-center text-sm font-semibold">
                {{ auth.user?.name?.charAt(0).toUpperCase() ?? '?' }}
              </span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint" />
            </button>
            <!-- Dropdown -->
            <div class="absolute right-0 top-full mt-2 w-56 card p-2 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
              <div class="px-3 py-2 border-b border-border mb-1">
                <p class="text-sm font-medium text-ink truncate">{{ auth.user?.name }}</p>
                <p class="text-xs text-ink-faint truncate">{{ auth.user?.email }}</p>
              </div>
              <NuxtLink to="/profile" class="nav-link">Профиль</NuxtLink>
              <NuxtLink to="/notifications" class="nav-link">Уведомления</NuxtLink>
              <button class="nav-link w-full text-left text-danger" @click="auth.logout()">Выйти</button>
            </div>
          </div>
        </template>

        <template v-else>
          <NuxtLink to="/login" class="btn-primary">Войти</NuxtLink>
        </template>
      </nav>
    </div>
  </header>
</template>
