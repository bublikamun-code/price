<script setup lang="ts">
const auth = useAuth()
const notifications = useNotifications()
const cart = useCartV2()
const theme = useTheme()
const isDark = computed(() => theme.mode.value === 'dark')

function openGlobalSearch() {
  if (import.meta.client) window.dispatchEvent(new CustomEvent('price:open-search'))
}
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border bg-surface lg:hidden">
    <div class="container-app flex min-h-14 items-center gap-2 px-3">
      <NuxtLink to="/dashboard" class="flex min-w-0 items-center gap-2" aria-label="Price Portal — кабинет">
        <span class="numeric text-base font-bold tracking-tight text-ink">PRICE<span class="text-action">/</span>WEB</span>
        <span class="hidden truncate text-xs text-ink-muted sm:inline">{{ auth.user?.company || 'Личный кабинет' }}</span>
      </NuxtLink>
      <span class="flex-1" />
      <UiIconButton label="Глобальный поиск" size="compact" variant="ghost" @click="openGlobalSearch">
        <Icon name="heroicons:magnifying-glass" class="size-5" aria-hidden="true" />
      </UiIconButton>
      <UiIconButton :label="isDark ? 'Включить светлую тему' : 'Включить тёмную тему'" size="compact" variant="ghost" @click="theme.toggle()">
        <Icon :name="isDark ? 'heroicons:sun' : 'heroicons:moon'" class="size-5" aria-hidden="true" />
      </UiIconButton>
      <NuxtLink to="/notifications" class="relative inline-flex size-10 items-center justify-center text-ink-muted hover:text-ink" aria-label="Уведомления">
        <Icon name="heroicons:bell" class="size-5" aria-hidden="true" />
        <span v-if="notifications.unreadCount.value" class="absolute right-1 top-1 min-w-4 border border-surface bg-danger px-1 text-xs leading-4 text-white">{{ notifications.unreadCount.value > 99 ? '99+' : notifications.unreadCount.value }}</span>
      </NuxtLink>
      <NuxtLink to="/cart" class="relative inline-flex size-10 items-center justify-center text-ink-muted hover:text-ink" aria-label="Текущая заявка">
        <Icon name="heroicons:clipboard-document-list" class="size-5" aria-hidden="true" />
        <span v-if="cart.store.cart?.totalItems" class="absolute right-0 top-0 min-w-4 border border-surface bg-action px-1 text-xs leading-4 text-action-on">{{ cart.store.cart.totalItems > 99 ? '99+' : cart.store.cart.totalItems }}</span>
      </NuxtLink>
      <NuxtLink to="/profile" class="inline-flex size-10 items-center justify-center text-ink-muted hover:text-ink" aria-label="Профиль">
        <Icon name="heroicons:user-circle" class="size-6" aria-hidden="true" />
      </NuxtLink>
    </div>
  </header>
</template>
