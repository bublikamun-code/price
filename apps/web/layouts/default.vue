<script setup lang="ts">
// Layout для публичных страниц (без sidebar).
// Авторизованные видят упрощённую шапку (AppHeader), гости — только «Войти».
// Мобильная нижняя навигация — у авторизованного клиента (как в client layout),
// чтобы на главной (/) меню было таким же, как на остальных страницах.
const auth = useAuth()
const showMobileNav = computed(() => !!auth.user && auth.isClient)

const bottomNavItems = [
  { to: '/', label: 'Главная', icon: 'heroicons:home' },
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/dashboard', label: 'Аналитика', icon: 'heroicons:bars-3' },
]
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <main class="flex-1" :class="{ 'pb-24 lg:pb-0': showMobileNav }">
      <slot />
    </main>
    <AppFooter />

    <!-- Нижняя навигация (mobile, только для авторизованного клиента):
         тот же «воздушный» компонент, что и в client layout -->
    <AppBottomNav v-if="showMobileNav" :items="bottomNavItems" />
  </div>
</template>
