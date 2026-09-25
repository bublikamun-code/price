<script setup lang="ts">
const auth = useAuth()
const notifications = useNotifications()
const cart = useCartV2()
const theme = useTheme()
const route = useRoute()
const isDark = computed(() => theme.mode.value === 'dark')

function openGlobalSearch() {
  if (import.meta.client) window.dispatchEvent(new CustomEvent('price:open-search'))
}

const onCurrencySection = computed(
  () => route.path === '/profile' && route.hash === '#profile-currency',
)
</script>

<template>
  <header class="sticky top-0 z-40 hidden border-b border-border bg-surface lg:block">
    <div class="container-app flex h-16 items-center gap-4 px-4">
      <NuxtLink to="/dashboard" class="flex shrink-0 items-center gap-2" aria-label="Price Portal — кабинет">
        <span class="numeric text-lg font-bold tracking-tight text-ink">PRICE<span class="text-action">/</span>WEB</span>
      </NuxtLink>
      <button
        type="button"
        class="inline-flex min-h-10 w-56 items-center gap-2 border border-border bg-surface-2 px-3 text-sm text-ink-muted transition-colors hover:border-border-strong hover:text-ink xl:w-72"
        aria-label="Глобальный поиск"
        @click="openGlobalSearch"
      >
        <Icon name="heroicons:magnifying-glass" class="size-5 shrink-0" aria-hidden="true" />
        <span class="truncate">Каталог и заявки</span>
      </button>
      <span class="flex-1" />
      <NuxtLink
        to="/profile#profile-currency"
        class="inline-flex min-h-10 items-center gap-2 px-2 text-sm font-semibold transition-colors hover:text-action"
        :class="onCurrencySection ? 'text-action' : 'text-ink-muted'"
        :aria-current="onCurrencySection ? 'page' : undefined"
      >
        <Icon name="heroicons:banknotes" class="size-5" aria-hidden="true" />
        <span class="numeric">{{ auth.user?.displayCurrency || 'BYN' }}</span>
      </NuxtLink>
      <NuxtLink to="/cart" class="relative inline-flex min-h-10 items-center gap-2 border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-2" aria-label="Текущая заявка">
        <Icon name="heroicons:clipboard-document-list" class="size-5" aria-hidden="true" />
        <span>Заявка</span>
        <span v-if="cart.store.cart?.totalItems" class="numeric border border-action bg-action px-1.5 text-xs text-action-on">{{ cart.store.cart.totalItems }}</span>
      </NuxtLink>
      <UiIconButton :label="isDark ? 'Включить светлую тему' : 'Включить тёмную тему'" variant="ghost" @click="theme.toggle()">
        <Icon :name="isDark ? 'heroicons:sun' : 'heroicons:moon'" class="size-5" aria-hidden="true" />
      </UiIconButton>
      <NuxtLink to="/notifications" class="relative inline-flex size-10 items-center justify-center text-ink-muted hover:text-ink" aria-label="Уведомления">
        <Icon name="heroicons:bell" class="size-5" aria-hidden="true" />
        <span v-if="notifications.unreadCount.value" class="absolute right-0 top-0 min-w-4 border border-surface bg-danger px-1 text-xs leading-4 text-white">{{ notifications.unreadCount.value > 99 ? '99+' : notifications.unreadCount.value }}</span>
      </NuxtLink>
      <NuxtLink to="/profile" class="inline-flex min-h-10 items-center gap-2 border-l border-border pl-4 text-sm font-semibold text-ink hover:text-action" :aria-label="`Профиль: ${auth.user?.name || ''}`">
        <Icon name="heroicons:user-circle" class="size-7" aria-hidden="true" />
        <span class="max-w-36 truncate">{{ auth.user?.name }}</span>
      </NuxtLink>
    </div>
  </header>
</template>
