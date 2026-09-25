<script setup lang="ts">
const auth = useAuth()
const { init: initFavorites } = useFavorites()
const { unreadCount } = useNotifications()
const theme = useTheme()

// Do not instantiate the v2 cart for guests or manager/admin sessions. If a
// guest signs in as a client without remounting, create it only after auth is known.
const cartV2 = shallowRef<ReturnType<typeof useCartV2> | null>(null)
if (auth.isClient) cartV2.value = useCartV2()

const cartCount = computed(() => cartV2.value?.store.cart?.totalItems ?? 0)
const themeIsDark = computed(() => theme.mode.value === 'dark')
const themeLabel = computed(() =>
  themeIsDark.value ? 'Включить светлую тему' : 'Включить тёмную тему',
)

// Keep the cart v2 counter responsive when the client cart changes.
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

const profileOpen = ref(false)
const profileTrigger = ref<HTMLButtonElement | null>(null)
const profileMenu = ref<HTMLElement | null>(null)

const route = useRoute()
watch(() => route.fullPath, () => {
  profileOpen.value = false
})

function openGlobalSearch() {
  if (import.meta.client) {
    window.dispatchEvent(new CustomEvent('price:open-search'))
  }
}

function toggleProfile() {
  profileOpen.value = !profileOpen.value
  if (profileOpen.value) nextTick(() => profileMenu.value?.querySelector<HTMLElement>('a, button')?.focus())
}

function closeProfile(restoreFocus = true) {
  profileOpen.value = false
  if (restoreFocus) nextTick(() => profileTrigger.value?.focus())
}

function onProfileKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeProfile()
  }
}

async function loadClientCart() {
  if (!auth.isClient || !auth.user?.id) return
  cartV2.value ??= useCartV2()
  try {
    // useCartV2 resolves the session/commercial owner before loading the cart.
    await cartV2.value.ensureLoaded()
  } catch {
    // The cart page surfaces the normalized v2 problem; the shell stays usable.
  }
}

onMounted(() => {
  // auth.session already confirmed the user cookie through /me. The v2 cart
  // request starts only after client auth is known and resolves session first.
  if (auth.isClient) {
    void loadClientCart()
    initFavorites()
  }
})

watch(
  () => [auth.isClient, auth.user?.id ?? null] as const,
  ([isClient, userId], [wasClient, previousUserId]) => {
    if (isClient === wasClient && userId === previousUserId) return
    if (!isClient || !userId) {
      cartV2.value?.reset()
      cartV2.value = null
      return
    }
    void loadClientCart()
    initFavorites()
  },
)

function getCompanyInitials(company: string | undefined, fallbackName: string | undefined): string {
  const source = (company || fallbackName || '?').trim()
  if (!source) return '?'
  const words = source.split(/\s+/).filter(Boolean)
  const chars = words.slice(0, 2).map(w => w.charAt(0).toUpperCase())
  return chars.join('') || source.charAt(0).toUpperCase()
}
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border bg-service text-ink-on-service">
    <div class="container-app flex min-h-16 items-center gap-3">
      <NuxtLink to="/" class="flex min-h-11 shrink-0 items-center gap-2" aria-label="Price Portal — главная">
        <span class="numeric text-lg font-bold text-ink-on-service">PRICE<span class="text-action">/</span>WEB</span>
      </NuxtLink>

      <span class="hidden h-6 w-px bg-white/20 sm:block" aria-hidden="true" />
      <span class="hidden text-xs font-semibold uppercase text-ink-on-service/70 sm:inline">Рабочий контур</span>
      <span class="flex-1" />

      <nav class="flex items-center gap-1" aria-label="Системная навигация">
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-2 border border-transparent px-3 text-sm font-semibold text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
          title="Поиск по каталогу (Ctrl+K)"
          aria-label="Открыть поиск по каталогу"
          aria-keyshortcuts="Control+K Meta+K"
          @click="openGlobalSearch"
        >
          <Icon name="heroicons:magnifying-glass" class="size-5" aria-hidden="true" />
          <span class="hidden lg:inline">Поиск</span>
          <kbd class="hidden border border-white/20 px-1.5 py-0.5 font-mono text-[10px] text-ink-on-service/70 xl:inline">CTRL K</kbd>
        </button>

        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-2 border border-transparent px-3 text-sm font-semibold text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
          :aria-label="themeLabel"
          :title="themeLabel"
          @click="theme.toggle()"
        >
          <Icon :name="themeIsDark ? 'heroicons:sun' : 'heroicons:moon'" class="size-5" aria-hidden="true" />
          <span class="hidden lg:inline">{{ themeIsDark ? 'Светлая' : 'Тёмная' }}</span>
        </button>

        <template v-if="auth.isAuthenticated">
          <NuxtLink
            to="/profile"
            class="hidden min-h-11 items-center border border-transparent px-3 text-sm font-semibold text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service sm:inline-flex"
            title="Валюта отображения — меняется в профиле"
          >
            {{ auth.user?.displayCurrency ?? 'BYN' }}
          </NuxtLink>

          <NuxtLink
            to="/notifications"
            class="relative inline-flex min-h-11 min-w-11 items-center justify-center border border-transparent text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
            aria-label="Уведомления"
            title="Уведомления"
          >
            <Icon name="heroicons:bell" class="size-5" aria-hidden="true" />
            <span
              v-if="unreadCount"
              class="absolute right-1 top-1 flex min-h-4 min-w-4 items-center justify-center border border-service bg-danger px-1 text-[10px] font-semibold text-white"
            >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </NuxtLink>

          <NuxtLink
            v-if="auth.isClient"
            to="/favorites"
            class="inline-flex min-h-11 min-w-11 items-center justify-center border border-transparent text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
            aria-label="Избранное"
            title="Избранное"
          >
            <Icon name="heroicons:heart" class="size-5" aria-hidden="true" />
          </NuxtLink>

          <NuxtLink
            v-if="auth.isClient"
            to="/cart"
            class="relative inline-flex min-h-11 min-w-11 items-center justify-center border border-transparent text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
            :class="{ 'cart-pop': cartPulse }"
            aria-label="Корзина"
            title="Корзина"
          >
            <Icon name="heroicons:shopping-cart" class="size-5" aria-hidden="true" />
            <span
              v-if="cartCount"
              class="absolute right-1 top-1 flex min-h-4 min-w-4 items-center justify-center border border-service bg-action px-1 text-[10px] font-semibold text-action-on"
            >{{ cartCount > 99 ? '99+' : cartCount }}</span>
          </NuxtLink>

          <div class="relative" @keydown="onProfileKeydown">
            <button
              ref="profileTrigger"
              type="button"
              class="inline-flex min-h-11 items-center gap-2 border border-transparent px-2 text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
              :aria-expanded="profileOpen"
              aria-haspopup="menu"
              aria-controls="app-profile-menu"
              aria-label="Открыть меню профиля"
              @click="toggleProfile"
            >
              <span class="flex size-8 items-center justify-center border border-white/20 bg-service-2 text-xs font-semibold text-ink-on-service">
                {{ getCompanyInitials(auth.user?.company, auth.user?.name) }}
              </span>
              <span class="hidden max-w-32 truncate text-sm font-semibold lg:inline">{{ auth.user?.name }}</span>
              <Icon name="heroicons:chevron-down" class="hidden size-4 sm:block" aria-hidden="true" />
            </button>
            <div v-if="profileOpen" class="fixed inset-0 z-40" @click="closeProfile(false)" />
            <div
              v-if="profileOpen"
              id="app-profile-menu"
              ref="profileMenu"
              class="absolute right-0 top-full z-50 mt-1 w-64 border border-border-strong bg-service p-2 shadow-overlay"
              role="menu"
              aria-label="Меню профиля"
            >
              <div class="border-b border-white/15 px-3 py-3">
                <p class="truncate text-sm font-semibold text-ink-on-service">{{ auth.user?.name }}</p>
                <p class="truncate text-xs text-ink-on-service/70">{{ auth.user?.email }}</p>
              </div>
              <NuxtLink to="/profile" class="nav-link mt-2" role="menuitem" @click="closeProfile(false)">Профиль</NuxtLink>
              <NuxtLink to="/notifications" class="nav-link" role="menuitem" @click="closeProfile(false)">Уведомления</NuxtLink>
              <button type="button" class="nav-link w-full text-left text-danger" role="menuitem" @click="closeProfile(false); auth.logout()">Выйти</button>
            </div>
          </div>
        </template>

        <NuxtLink v-else to="/login" class="inline-flex min-h-11 items-center border border-action bg-action px-4 text-sm font-bold text-action-on transition-colors hover:bg-action-hover">
          Войти
        </NuxtLink>
      </nav>
    </div>
  </header>
</template>

<style scoped>
.cart-pop {
  animation: cart-pop 0.7s ease;
}
@keyframes cart-pop {
  0% { transform: scale(1); }
  40% { transform: scale(1.08); }
  100% { transform: scale(1); }
}
</style>
