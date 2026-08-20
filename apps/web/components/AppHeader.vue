<script setup lang="ts">
// Глобальная шапка. Состав зависит от роли — см. SITEMAP.md §2.
const auth = useAuth()
const { count: cartCount, refresh: refreshCart } = useCart()
const { unreadCount, refresh: refreshNotifications, startPolling } = useNotifications()

onMounted(() => {
  if (auth.isClient) refreshCart()
  if (auth.isAuthenticated) {
    refreshNotifications()
    startPolling() // поллинг бейджа (60 с); тики без сессии пропускаются
  }
})
</script>

<template>
  <header class="sticky top-0 z-40 h-16 border-b border-border bg-surface/80 backdrop-blur-md">
    <div class="container-app h-full flex items-center gap-4">
      <!-- Logo -->
      <NuxtLink to="/" class="flex items-center gap-2 shrink-0">
        <span class="font-display text-xl font-bold">
          <span class="text-primary">Price</span><span class="text-ink">Portal</span>
        </span>
      </NuxtLink>

      <!-- Search (только авторизованным) -->
      <div v-if="auth.isAuthenticated" class="hidden md:flex flex-1 max-w-md">
        <div class="relative w-full">
          <Icon name="heroicons:magnifying-glass" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint" />
          <input
            type="search"
            placeholder="Поиск по артикулу, наименованию..."
            class="input pl-10"
            @keyup.enter="(e) => navigateTo({ path: '/catalog', query: { q: (e.target as HTMLInputElement).value } })"
          >
        </div>
      </div>

      <div v-else class="flex-1"/>

      <!-- Правая часть -->
      <nav class="flex items-center gap-1 sm:gap-2">
        <template v-if="auth.isAuthenticated">
          <!-- Валюта (клиент) -->
          <button class="btn-ghost px-3 hidden sm:inline-flex" title="Display-валюта">
            <span class="badge-info">BYN</span>
          </button>

          <!-- Уведомления -->
          <button class="btn-ghost p-2.5 relative" title="Уведомления" @click="navigateTo('/notifications')">
            <Icon name="heroicons:bell" class="w-5 h-5" />
            <span v-if="unreadCount" class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-danger text-white text-[10px] font-semibold rounded-pill flex items-center justify-center">
              {{ unreadCount > 99 ? '99+' : unreadCount }}
            </span>
          </button>

          <!-- Корзина (клиент) -->
          <NuxtLink v-if="auth.isClient" to="/cart" class="btn-ghost p-2.5 relative" title="Корзина">
            <Icon name="heroicons:shopping-cart" class="w-5 h-5" />
            <span v-if="cartCount" class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-primary text-white text-[10px] font-semibold rounded-pill flex items-center justify-center">
              {{ cartCount }}
            </span>
          </NuxtLink>

          <!-- Профиль -->
          <div class="relative group">
            <button class="flex items-center gap-2 px-2 py-1.5 rounded-pill hover:bg-canvas transition-colors">
              <span class="w-8 h-8 rounded-pill bg-secondary-soft text-secondary flex items-center justify-center text-sm font-semibold">
                {{ auth.user?.name?.charAt(0).toUpperCase() ?? '?' }}
              </span>
              <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint" />
            </button>
            <!-- Dropdown -->
            <div class="absolute right-0 top-full mt-2 w-56 card p-2 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
              <div class="px-3 py-2 border-b border-border mb-1">
                <p class="text-sm font-medium text-ink truncate">{{ auth.user?.name }}</p>
                <p class="text-xs text-ink-faint truncate">{{ auth.user?.email }}</p>
              </div>
              <NuxtLink to="/profile" class="nav-link">Профиль</NuxtLink>
              <NuxtLink to="/notifications" class="nav-link">Уведомления</NuxtLink>
              <button class="nav-link w-full text-left text-danger" @click="auth.logout()">Выйти</button>
            </div>
          </div>
        </template>

        <template v-else>
          <NuxtLink to="/login" class="btn-primary">Войти</NuxtLink>
        </template>
      </nav>
    </div>
  </header>
</template>
