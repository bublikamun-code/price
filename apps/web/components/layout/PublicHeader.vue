<script setup lang="ts">
const auth = useAuth()
const theme = useTheme()
const themeIsDark = computed(() => theme.mode.value === 'dark')
const themeLabel = computed(() =>
  themeIsDark.value ? 'Включить светлую тему' : 'Включить тёмную тему',
)

function openSearch() {
  if (import.meta.client) window.dispatchEvent(new CustomEvent('price:open-search'))
}
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border bg-service text-ink-on-service">
    <div class="container-app flex min-h-16 items-center gap-4">
      <NuxtLink to="/" class="flex min-h-11 shrink-0 items-center gap-2" aria-label="Price Portal — главная">
        <span class="numeric text-lg font-bold text-ink-on-service">PRICE<span class="text-action">/</span>WEB</span>
      </NuxtLink>

      <nav class="hidden items-center gap-1 md:flex" aria-label="Основная навигация">
        <NuxtLink to="/brands" class="inline-flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-semibold text-ink-on-service/70 hover:border-action hover:text-ink-on-service">Каталог</NuxtLink>
        <NuxtLink to="/news" class="inline-flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-semibold text-ink-on-service/70 hover:border-action hover:text-ink-on-service">Новости</NuxtLink>
      </nav>

      <span class="flex-1" />

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-2 border border-transparent px-3 text-sm font-semibold text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
          title="Поиск по порталу (Ctrl+K)"
          aria-label="Открыть поиск по порталу"
          aria-keyshortcuts="Control+K Meta+K"
          @click="openSearch"
        >
          <Icon name="heroicons:magnifying-glass" class="size-5" aria-hidden="true" />
          <span class="hidden lg:inline">Поиск</span>
        </button>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center border border-transparent px-3 text-ink-on-service/70 transition-colors hover:border-white/20 hover:bg-service-2 hover:text-ink-on-service"
          :aria-label="themeLabel"
          :title="themeLabel"
          @click="theme.toggle()"
        >
          <Icon :name="themeIsDark ? 'heroicons:sun' : 'heroicons:moon'" class="size-5" aria-hidden="true" />
        </button>
        <NuxtLink
          v-if="auth.isAuthenticated"
          to="/dashboard"
          class="hidden min-h-11 items-center border border-white/25 px-3 text-sm font-semibold text-ink-on-service transition-colors hover:bg-service-2 sm:inline-flex"
        >Кабинет</NuxtLink>
        <NuxtLink
          v-else
          to="/login"
          class="inline-flex min-h-11 items-center border border-action bg-action px-4 text-sm font-bold text-action-on transition-colors hover:bg-action-hover"
        >Войти</NuxtLink>
      </div>
    </div>
  </header>
</template>
