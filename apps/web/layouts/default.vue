<script setup lang="ts">
// Layout для публичных страниц (без sidebar).
// Авторизованные видят упрощённую шапку (AppHeader), гости — только «Войти».
// Мобильная нижняя навигация — у авторизованного клиента (как в client layout),
// чтобы на главной (/) меню было таким же, как на остальных страницах.
const route = useRoute()
const auth = useAuth()
const showMobileNav = computed(() => auth.isAuthenticated && auth.isClient)

const bottomNavItems = [
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/dashboard', label: 'Меню', icon: 'heroicons:bars-3' },
]

function isActive(to: string) {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <main class="flex-1" :class="{ 'pb-16 lg:pb-0': showMobileNav }">
      <slot />
    </main>
    <AppFooter />

    <!-- Нижняя навигация (mobile, только для авторизованного клиента) -->
    <nav
      v-if="showMobileNav"
      class="fixed bottom-0 left-0 right-0 bg-surface border-t border-border z-40 px-4 py-2 lg:hidden pb-[env(safe-area-inset-bottom)]"
    >
      <div class="flex items-center justify-around">
        <NuxtLink
          v-for="item in bottomNavItems"
          :key="item.to"
          :to="item.to"
          class="flex flex-col items-center gap-0.5 p-1 text-xs font-medium transition-colors"
          :class="isActive(item.to) ? 'text-primary' : 'text-ink-muted hover:text-ink'"
        >
          <Icon :name="item.icon" class="w-5 h-5" />
          <span>{{ item.label }}</span>
        </NuxtLink>
      </div>
    </nav>
  </div>
</template>
