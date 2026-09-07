<script setup lang="ts">
// Глобальная шапка. Состав зависит от роли — см. SITEMAP.md §2.
import type { AuthUser } from '~/composables/useAuth'

const auth = useAuth()
const { refresh: refreshCart, count: cartCount } = useCart()
const { init: initFavorites } = useFavorites()
const { unreadCount } = useNotifications()

// Пульс значка корзины при добавлении позиции (count растёт).
const cartPulse = ref(false)
let cartPulseTimer: ReturnType<typeof setTimeout> | undefined
watch(cartCount, (n, prev) => {
  if (n <= (prev ?? 0)) return
  cartPulse.value = false
  requestAnimationFrame(() => {
    cartPulse.value = true
    clearTimeout(cartPulseTimer)
    cartPulseTimer = setTimeout(() => { cartPulse.value = false }, 700)
  })
})

const searchOpen = ref(false)
const profileOpen = ref(false)
const desktopSearchOpen = ref(false)
const mobileSearchTop = ref(72) // низ плавающей карточки шапки (12 + 56 + зазор)

const STOCK_LABEL: Record<string, string> = {
  IN_STOCK: 'В наличии',
  PREORDER: 'Под заказ',
  ARCHIVED: 'Архив',
}

const { thumbOf } = useProductPhoto()

const desktop = useSearchTypeahead()
const mobile = useSearchTypeahead()

function closeSearch() {
  searchOpen.value = false
  mobile.clear()
}

function closeDesktopSearch() {
  desktopSearchOpen.value = false
  desktop.clear()
}

const route = useRoute()
watch(() => route.fullPath, () => {
  if (searchOpen.value) closeSearch()
  if (desktopSearchOpen.value) closeDesktopSearch()
})

onMounted(() => {
  if (!auth.isAuthenticated) {
    const tokenC = useCookie<string | null>('auth_token')
    const userC = useCookie<AuthUser | null>('auth_user')
    if (tokenC.value && userC.value) {
      auth.token = tokenC.value
      auth.user = userC.value
      auth.fetchMe().catch(() => {})
    }
  }

  if (auth.isClient) {
    refreshCart()
    initFavorites()
  }
})

function getCompanyInitials(company: string | undefined, fallbackName: string | undefined): string {
  const source = (company || fallbackName || '?').trim()
  if (!source) return '?'
  const words = source.split(/\s+/).filter(Boolean)
  const chars = words.slice(0, 2).map(w => w.charAt(0).toUpperCase())
  return chars.join('') || source.charAt(0).toUpperCase()
}
</script>

<template>
  <header class="sticky top-0 z-40">
    <!-- Шапка — карточка в стиле остальных блоков портала, «плавает»
         над контентом при скролле -->
    <div class="container-app py-3">
      <div class="glass flex items-center gap-2 px-4 h-14">
      <NuxtLink to="/" class="flex items-center gap-2 shrink-0">
        <span class="text-base sm:text-lg font-bold">
          <span class="text-primary">Price</span><span class="text-ink">Portal</span>
        </span>
      </NuxtLink>

      <div class="flex-1" />

      <nav class="flex items-center gap-1 sm:gap-2">
        <template v-if="auth.isAuthenticated">
          <button
            class="btn-ghost px-3 hidden sm:inline-flex"
            title="Валюта отображения — меняется в профиле"
          >
            <span class="badge-info">{{ auth.user?.displayCurrency ?? 'BYN' }}</span>
          </button>

          <button class="btn-ghost p-2 sm:p-2.5 relative" title="Уведомления">
            <Icon name="heroicons:bell" class="w-5 h-5" />
            <span
              v-if="unreadCount"
              class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-danger text-white text-[10px] font-semibold rounded-pill flex items-center justify-center"
            >
              {{ unreadCount > 99 ? '99+' : unreadCount }}
            </span>
          </button>

          <NuxtLink v-if="auth.isClient" to="/favorites" class="btn-ghost p-2 sm:p-2.5" title="Избранное">
            <Icon name="heroicons:heart" class="w-5 h-5" />
          </NuxtLink>

          <NuxtLink
            v-if="auth.isClient"
            to="/cart"
            class="btn-ghost p-2 sm:p-2.5 relative"
            :class="{ 'cart-pop': cartPulse }"
            title="Корзина"
          >
            <Icon name="heroicons:shopping-cart" class="w-5 h-5" />
            <span
              v-if="cartCount"
              class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-primary text-white text-[10px] font-semibold rounded-pill flex items-center justify-center"
            >
              {{ cartCount > 99 ? '99+' : cartCount }}
            </span>
          </NuxtLink>

          <button
            class="btn-ghost p-2.5 shrink-0 hidden sm:inline-flex"
            title="Поиск по каталогу"
            @click="desktopSearchOpen = true"
          >
            <Icon name="heroicons:magnifying-glass" class="w-5 h-5" />
          </button>

          <div class="flex items-center sm:hidden">
            <button
              class="btn-ghost p-2 sm:p-2.5 shrink-0"
              :title="searchOpen ? 'Закрыть поиск' : 'Поиск по каталогу'"
              @click="searchOpen = !searchOpen"
            >
              <Icon :name="searchOpen ? 'heroicons:x-mark' : 'heroicons:magnifying-glass'" class="w-5 h-5" />
            </button>
          </div>

          <div
            v-if="searchOpen"
            class="fixed inset-x-0 bottom-0 z-50 glass rounded-none p-4 flex flex-col sm:hidden"
            :style="{ top: mobileSearchTop + 'px' }"
          >
            <div class="flex items-center gap-2">
              <div class="relative flex-1">
                <Icon name="heroicons:magnifying-glass" class="w-5 h-5 absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none" />
                <input
                  v-model="mobile.query"
                  type="search"
                  role="combobox"
                  :aria-expanded="mobile.open"
                  aria-haspopup="listbox"
                  placeholder="Поиск по каталогу..."
                  class="input w-full h-11 pl-10"
                  @input="mobile.onInput"
                  @keydown="mobile.onKeydown"
                >
              </div>
              <button class="btn-ghost p-2.5 shrink-0" title="Закрыть поиск" @click="closeSearch">
                <Icon name="heroicons:x-mark" class="w-5 h-5" />
              </button>
            </div>

            <div v-if="mobile.open" class="flex-1 overflow-y-auto scrollbar-none mt-3 -mx-4 px-4 space-y-1" role="listbox">
              <template v-if="mobile.results.length">
                <button
                  v-for="(p, i) in mobile.results"
                  :key="p.id"
                  class="w-full flex items-center gap-3 px-3 py-3 rounded-xl text-left transition-colors"
                  :class="[i === mobile.active ? 'bg-surface-2' : 'hover:bg-canvas']"
                  role="option"
                  :aria-selected="i === mobile.active"
                  @click="mobile.goProduct(p)"
                >
                  <img
                    v-if="thumbOf(p.photo_key)"
                    :src="thumbOf(p.photo_key) ?? undefined"
                    :alt="p.name"
                    class="w-14 h-14 rounded-lg object-contain shrink-0 bg-canvas"
                  >
                  <span v-else class="w-14 h-14 rounded-lg bg-canvas text-ink-faint flex items-center justify-center shrink-0">
                    <Icon name="heroicons:photo" class="w-7 h-7" />
                  </span>
                  <span class="min-w-0 flex-1">
                    <span class="block text-sm font-medium text-ink leading-snug line-clamp-2">{{ p.name }}</span>
                    <span class="block text-xs text-ink-faint mt-0.5">{{ p.sku }}</span>
                  </span>
                  <span class="text-right shrink-0">
                    <span class="block text-base font-semibold text-ink">{{ formatMoney(mobile.displayPrice(p), p.currency) }}</span>
                    <span class="block text-xs text-ink-faint mt-0.5">{{ STOCK_LABEL[p.stock_status] || p.stock_status }}</span>
                  </span>
                </button>
              </template>
              <p v-else-if="!mobile.loading" class="px-3 py-8 text-sm text-ink-faint text-center">
                Ничего не найдено
              </p>
              <p v-else class="px-3 py-8 text-sm text-ink-faint text-center opacity-60">
                Загрузка...
              </p>
            </div>
            <p v-else-if="mobile.query.trim().length < 2" class="mt-6 text-sm text-ink-faint text-center">
              Начните вводить название или артикул
            </p>
          </div>

          <div class="relative">
            <button
              class="flex items-center gap-1.5 px-1.5 py-1 rounded-pill hover:bg-canvas transition-colors"
              @click="profileOpen = !profileOpen"
            >
              <span class="w-7 h-7 rounded-pill bg-surface-2 text-ink flex items-center justify-center text-xs font-semibold">
                {{ getCompanyInitials(auth.user?.company, auth.user?.name) }}
              </span>
              <Icon name="heroicons:chevron-down" class="w-3.5 h-3.5 text-ink-faint hidden sm:block" />
            </button>
            <!-- Оверлей закрытия — внутри той же relative-обёртки: на уровне
                 document он z-40 равен шапке и перекрывал пункты меню кликом.
                 Здесь он ниже меню (z-50) в общем контексте шапки. -->
            <div v-if="profileOpen" class="fixed inset-0" @click="profileOpen = false" />
            <!-- Меню профиля: внутри relative-обёртки, иначе absolute улетает
                 вниз страницы (positioned-предок — вся страница, а не шапка) -->
            <div v-if="profileOpen" class="absolute right-0 top-full mt-2 w-56 glass p-2 z-50">
              <div class="px-3 py-2 border-b border-border mb-1">
                <p class="text-sm font-medium text-ink truncate">{{ auth.user?.name }}</p>
                <p class="text-xs text-ink-faint truncate">{{ auth.user?.email }}</p>
              </div>
              <NuxtLink to="/profile" class="nav-link" @click="profileOpen = false">Профиль</NuxtLink>
              <NuxtLink to="/notifications" class="nav-link" @click="profileOpen = false">Уведомления</NuxtLink>
              <button class="nav-link w-full text-left text-danger" @click="auth.logout()">Выйти</button>
            </div>
          </div>
        </template>

        <template v-else>
          <NuxtLink to="/login" class="btn-primary">Войти</NuxtLink>
        </template>
      </nav>
      </div>
    </div>
  </header>

  <Teleport to="body">
    <div v-if="desktopSearchOpen" class="fixed inset-0 z-50 flex items-start justify-center">
      <div class="absolute inset-0 bg-ink/40 backdrop-blur-sm" @click="closeDesktopSearch" />
      <div class="relative w-full max-w-2xl mx-4 mt-20 glass p-0 overflow-hidden">
        <div class="flex items-center gap-3 px-5 py-4 border-b border-border">
          <Icon name="heroicons:magnifying-glass" class="w-5 h-5 text-ink-faint shrink-0" />
          <input
            v-model="desktop.query"
            type="search"
            role="combobox"
            :aria-expanded="desktop.open"
            aria-haspopup="listbox"
            placeholder="Поиск по каталогу..."
            class="flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-faint"
            @input="desktop.onInput"
            @keydown="desktop.onKeydown"
          >
          <button class="btn-ghost p-1.5 shrink-0" title="Закрыть" @click="closeDesktopSearch">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div v-if="desktop.open" class="max-h-96 overflow-y-auto scrollbar-none p-2" role="listbox">
          <template v-if="desktop.results.length">
            <button
              v-for="(p, i) in desktop.results"
              :key="p.id"
              class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-colors"
              :class="[i === desktop.active ? 'bg-surface-2' : 'hover:bg-canvas']"
              role="option"
              :aria-selected="i === desktop.active"
              @click="desktop.goProduct(p)"
            >
              <img
                v-if="thumbOf(p.photo_key)"
                :src="thumbOf(p.photo_key) ?? undefined"
                :alt="p.name"
                class="w-12 h-12 rounded-lg object-contain shrink-0 bg-canvas"
              >
              <span v-else class="w-12 h-12 rounded-lg bg-canvas text-ink-faint flex items-center justify-center shrink-0">
                <Icon name="heroicons:photo" class="w-6 h-6" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-medium text-ink truncate">{{ p.name }}</span>
                <span class="block text-xs text-ink-faint mt-0.5">
                  {{ p.sku }}
                  <template v-if="p.brand"> · {{ p.brand.name }}</template>
                </span>
              </span>
              <span class="text-right shrink-0">
                <span class="block text-sm font-semibold text-ink">{{ formatMoney(desktop.displayPrice(p), p.currency) }}</span>
                <span class="block text-xs text-ink-faint mt-0.5">{{ STOCK_LABEL[p.stock_status] || p.stock_status }}</span>
              </span>
            </button>
          </template>
          <p v-else-if="!desktop.loading" class="px-4 py-8 text-sm text-ink-faint text-center">
            Ничего не найдено
          </p>
          <p v-else class="px-4 py-8 text-sm text-ink-faint text-center opacity-60">
            Загрузка...
          </p>
        </div>
        <p v-else-if="desktop.query.trim().length < 2" class="px-5 py-6 text-sm text-ink-faint text-center">
          Начните вводить название или артикул
        </p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Пульс значка корзины при добавлении товара */
.cart-pop {
  animation: cart-pop 0.7s ease;
}
@keyframes cart-pop {
  0% { transform: scale(1); }
  40% { transform: scale(1.3); }
  100% { transform: scale(1); }
}
</style>
