<script setup lang="ts">
// Layout Telegram Mini App: контент в колонке max-w-md + нижняя навигация (4 пункта).
// Приватная зона (Mini App) не индексируется; подключаем telegram-web-app.js.
useHead({
  // Приватная зона (Mini App) не индексируется.
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
  script: [{ src: 'https://telegram.org/js/telegram-web-app.js' }],
})
useAuth()
const { count: cartCount, refresh: refreshCart } = useCart()
const { unreadCount } = useNotifications()
const route = useRoute()

onMounted(() => {
  if (useAuth().isAuthenticated) refreshCart()
})

const NAV = [
  { to: '/m/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/m/cart', label: 'Корзина', icon: 'heroicons:shopping-cart' },
  { to: '/m/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
  { to: '/m/notifications', label: 'Уведомления', icon: 'heroicons:bell' },
]

function isActive(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <div class="min-h-screen bg-canvas flex flex-col">
    <main class="flex-1 w-full max-w-md mx-auto px-4 pb-[calc(5rem_+_env(safe-area-inset-bottom))] pt-[calc(1rem_+_env(safe-area-inset-top))]">
      <slot />
    </main>

    <nav class="fixed bottom-0 inset-x-0 z-40 bg-surface/95 backdrop-blur border-t border-border" style="padding-bottom: env(safe-area-inset-bottom)">
      <div class="max-w-md mx-auto grid grid-cols-4">
        <NuxtLink
          v-for="item in NAV"
          :key="item.to"
          :to="item.to"
          class="flex flex-col items-center justify-center gap-0.5 h-12 text-[10px] font-medium transition-colors"
          :class="isActive(item.to) ? 'text-primary' : 'text-ink-muted active:text-primary'"
        >
          <span class="relative">
            <Icon :name="item.icon" class="w-5 h-5" />
            <span
              v-if="item.to === '/m/cart' && cartCount > 0"
              class="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-pill bg-primary text-white text-[9px] leading-4 text-center font-semibold"
            >{{ cartCount > 99 ? '99+' : cartCount }}</span>
            <span
              v-else-if="item.to === '/m/notifications' && unreadCount > 0"
              class="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-pill bg-primary text-white text-[9px] leading-4 text-center font-semibold"
            >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </span>
          <span>{{ item.label }}</span>
        </NuxtLink>
      </div>
    </nav>
  </div>
</template>
