<script setup lang="ts">
useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
  script: [{ src: 'https://telegram.org/js/telegram-web-app.js' }],
})

// Telegram Mini App — изолированный v1-канал. Browser-корзина v2 не смешивается с этим состоянием.
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
  { to: '/m/notifications', label: 'События', icon: 'heroicons:bell' },
]

function isActive(to: string) {
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <div class="min-h-screen bg-background text-ink">
    <main
      class="mx-auto w-full max-w-md px-4 pb-[calc(4.75rem+env(safe-area-inset-bottom))] pt-[calc(1rem+env(safe-area-inset-top))]"
    >
      <slot />
    </main>
    <nav
      class="fixed inset-x-0 bottom-0 z-40 border-t border-border-strong bg-service text-ink-on-service"
      aria-label="Навигация Mini App"
      :style="{ paddingBottom: 'env(safe-area-inset-bottom)' }"
    >
      <div class="mx-auto grid max-w-md grid-cols-4">
        <NuxtLink
          v-for="item in NAV"
          :key="item.to"
          :to="item.to"
          class="relative flex min-h-14 flex-col items-center justify-center gap-0.5 border-t-2 px-1 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-white"
          :class="isActive(item.to) ? 'border-action bg-white/10 text-white' : 'border-transparent text-ink-on-service/70 hover:bg-white/10 hover:text-white'"
          :aria-current="isActive(item.to) ? 'page' : undefined"
        >
          <span class="relative">
            <Icon :name="item.icon" class="size-5" aria-hidden="true" />
            <span
              v-if="item.to === '/m/cart' && cartCount > 0"
              class="numeric absolute -right-3 -top-1 min-w-4 bg-action px-1 text-center text-xs font-bold leading-4 text-white"
            >{{ cartCount > 99 ? '99+' : cartCount }}</span>
            <span
              v-else-if="item.to === '/m/notifications' && unreadCount > 0"
              class="numeric absolute -right-3 -top-1 min-w-4 bg-action px-1 text-center text-xs font-bold leading-4 text-white"
            >{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </span>
          <span>{{ item.label }}</span>
        </NuxtLink>
      </div>
    </nav>
  </div>
</template>
