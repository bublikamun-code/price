<script setup lang="ts">
// Layout авторизованного клиента: шапка + sidebar (desktop) + нижняя навигация (mobile) + контент.
// Навигация — см. SITEMAP.md §2. Sidebar — компонент AppSidebar (тот же и на главной).
// Приватная зона не индексируется (публичная SEO-витрина только на /brands).
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

// Нижняя навигация для мобильных (<lg) — 4 пункта, «Аналитика» ведёт на /dashboard.
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
    <!-- Вся строка (сайдбар + контент) — в одном контейнере с шапкой,
         чтобы карточка шапки и колонка контента были строго друг под другом -->
    <div class="flex-1 flex justify-center">
      <div class="container-app flex">
        <AppSidebar />

        <!-- Content -->
        <main class="flex-1 min-w-0 py-6 lg:py-8 pb-24 lg:pb-0">
          <slot />
        </main>
      </div>
    </div>
    <AppFooter />
    <AppCartPopup />

    <!-- Нижняя навигация (mobile): плавающая карточка, состав — для клиента -->
    <AppBottomNav :items="bottomNavItems" />
  </div>
</template>
