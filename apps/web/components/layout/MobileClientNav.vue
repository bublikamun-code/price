<script setup lang="ts">
const route = useRoute()
const cart = useCartV2()
const items = computed(() => [
  { to: '/catalog', label: 'Каталог', icon: 'heroicons:squares-2x2' },
  { to: '/cart', label: 'Заявка', icon: 'heroicons:clipboard-document-list', count: cart.store.cart?.totalItems ?? 0 },
  { to: '/dashboard', label: 'Кабинет', icon: 'heroicons:building-office-2' },
  { to: '/profile', label: 'Профиль', icon: 'heroicons:user-circle' },
])

function isActive(to: string): boolean {
  return route.path === to || route.path.startsWith(`${to}/`)
}

const root = shallowRef<HTMLElement | null>(null)
useNavLayer(root)
</script>

<template>
  <nav
    ref="root"
    class="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface lg:hidden"
    :style="{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }"
    aria-label="Основная навигация"
  >
    <div class="mx-auto grid h-[var(--h-mobile-nav)] max-w-lg grid-cols-4">
      <NuxtLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        class="relative flex h-full flex-col items-center justify-center gap-1 border-t-2 px-1 text-xs font-semibold transition-colors"
        :class="isActive(item.to) ? 'border-action text-action' : 'border-transparent text-ink-muted'"
        :aria-current="isActive(item.to) ? 'page' : undefined"
      >
        <span class="relative">
          <Icon :name="item.icon" class="size-5" aria-hidden="true" />
          <span
            v-if="item.count"
            class="absolute -right-2.5 -top-2 min-w-4 border border-surface bg-action px-1 text-xs leading-4 text-action-on"
            :aria-label="`Позиций в заявке: ${item.count}`"
          >{{ item.count > 99 ? '99+' : item.count }}</span>
        </span>
        <span class="truncate">{{ item.label }}</span>
      </NuxtLink>
    </div>
  </nav>
</template>
