<script setup lang="ts">
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

const route = useRoute()
const auth = useAuth()
/** Мобильная панель разделов (выезжает слева). На десктопе — постоянный сайдбар. */
const navOpen = ref(false)

// Пункты сгруппированы по смыслу: 13 разделов плоским списком читались плохо,
// особенно в мобильной панели, где места мало.
const navSections = [
  {
    label: 'Работа',
    items: [
      { to: '/manager', label: 'Обзор', icon: 'heroicons:chart-bar' },
      { to: '/manager/orders', label: 'Заявки', icon: 'heroicons:clipboard-document-list' },
      { to: '/manager/quotes', label: 'КП', icon: 'heroicons:document-text' },
    ],
  },
  {
    label: 'Клиенты',
    items: [
      { to: '/manager/organizations', label: 'Организации', icon: 'heroicons:building-office-2' },
      { to: '/manager/users', label: 'Клиенты', icon: 'heroicons:users' },
    ],
  },
  {
    label: 'Контент',
    items: [
      { to: '/manager/catalog', label: 'Каталог', icon: 'heroicons:archive-box' },
      { to: '/manager/import', label: 'Импорт прайса', icon: 'heroicons:arrow-up-tray' },
      { to: '/manager/files', label: 'Файлы', icon: 'heroicons:folder' },
      { to: '/manager/brands', label: 'Бренды и серии', icon: 'heroicons:tag' },
      { to: '/manager/banners', label: 'Баннеры', icon: 'heroicons:rectangle-stack' },
      { to: '/manager/news', label: 'Новости', icon: 'heroicons:newspaper' },
    ],
  },
  {
    label: 'Система',
    items: [
      { to: '/manager/currency', label: 'Курсы валют', icon: 'heroicons:banknotes' },
      { to: '/manager/audit', label: 'Аудит', icon: 'heroicons:shield-check' },
    ],
  },
]
const adminNavItem = { to: '/manager/admin', label: 'Администрирование', icon: 'heroicons:cog-6-tooth' }
const roleLabel = computed(() => auth.user?.role === 'ADMIN' ? 'Администратор' : 'Менеджер')

function isActive(to: string) {
  return to === '/manager' ? route.path === to : route.path.startsWith(to)
}

// Переход в раздел закрывает мобильную панель — иначе она остаётся поверх
// только что открывшейся страницы.
watch(() => route.fullPath, () => {
  navOpen.value = false
})
</script>

<template>
  <div class="min-h-screen bg-background text-ink">
    <header class="sticky top-0 z-40 border-b border-border-strong bg-service text-ink-on-service">
      <div class="mx-auto flex h-16 max-w-[1440px] items-center gap-4 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          class="inline-flex size-11 shrink-0 items-center justify-center border border-transparent text-ink-on-service hover:border-border-strong hover:bg-service-2 lg:hidden"
          aria-label="Открыть меню разделов"
          :aria-expanded="navOpen"
          aria-controls="manager-mobile-nav"
          @click="navOpen = true"
        >
          <Icon name="heroicons:bars-3" class="size-5" aria-hidden="true" />
        </button>

        <NuxtLink to="/manager" class="flex min-w-0 items-center gap-3" aria-label="Price Web, управление">
          <span class="grid size-8 grid-cols-3 items-end gap-0.5 border border-ink-on-service/30 p-1" aria-hidden="true">
            <i class="h-2 bg-ink-on-service" />
            <i class="h-4 bg-ink-on-service" />
            <i class="h-3 bg-ink-on-service" />
          </span>
          <span class="min-w-0">
            <strong class="block text-sm font-extrabold leading-4">PRICE WEB</strong>
            <span class="block text-xs leading-4 text-ink-on-service/70">Управление</span>
          </span>
        </NuxtLink>

        <div class="ml-auto flex items-center gap-2">
          <span class="hidden border border-ink-on-service/25 px-2 py-1 text-xs font-semibold sm:inline-flex">{{ roleLabel }}</span>
          <button
            v-if="auth.user"
            type="button"
            class="inline-flex min-h-11 items-center gap-2 border border-ink-on-service/25 px-3 text-sm font-semibold text-ink-on-service hover:bg-service-2"
            @click="auth.logout"
          >
            <Icon name="heroicons:arrow-right-start-on-rectangle" class="size-4" aria-hidden="true" />
            <span class="hidden sm:inline">Выйти</span>
          </button>
        </div>
      </div>
    </header>

    <div class="mx-auto flex max-w-[1440px]">
      <aside
        class="sticky top-16 hidden h-[calc(100vh-4rem)] w-60 shrink-0 border-r border-border-strong bg-service text-ink-on-service lg:block"
        aria-label="Разделы управления"
      >
        <nav class="flex h-full flex-col overflow-y-auto p-3" aria-label="Разделы управления">
          <div v-for="section in navSections" :key="section.label" class="mb-4 last:mb-0">
            <p class="mb-1 px-3 text-xs font-bold uppercase tracking-[0.16em] text-ink-on-service/60">
              {{ section.label }}
            </p>
            <NuxtLink
              v-for="item in section.items"
              :key="item.to"
              :to="item.to"
              class="nav-link"
              :class="isActive(item.to) ? 'nav-link-active border-l-2 border-l-action' : ''"
              :aria-current="isActive(item.to) ? 'page' : undefined"
            >
              <Icon :name="item.icon" class="size-5 shrink-0" aria-hidden="true" />
              <span>{{ item.label }}</span>
            </NuxtLink>
          </div>

          <div v-if="auth.isAdmin" class="mt-auto border-t border-ink-on-service/20 pt-3">
            <NuxtLink
              :to="adminNavItem.to"
              class="nav-link"
              :class="isActive(adminNavItem.to) ? 'nav-link-active border-l-2 border-l-action' : ''"
              :aria-current="isActive(adminNavItem.to) ? 'page' : undefined"
            >
              <Icon :name="adminNavItem.icon" class="size-5 shrink-0" aria-hidden="true" />
              <span>{{ adminNavItem.label }}</span>
            </NuxtLink>
          </div>
        </nav>
      </aside>

      <!-- Мобильная панель разделов: список, а не горизонтальная лента поверх контента. -->
      <UiSheet
        v-model:open="navOpen"
        side="left"
        title="Разделы управления"
        description="Переход между разделами кабинета менеджера"
      >
        <nav id="manager-mobile-nav" class="flex flex-col gap-4" aria-label="Мобильная навигация управления">
          <div v-for="section in navSections" :key="section.label">
            <p class="mb-1 px-3 text-xs font-bold uppercase tracking-[0.16em] text-ink-muted">
              {{ section.label }}
            </p>
            <div class="space-y-1">
              <NuxtLink
                v-for="item in section.items"
                :key="item.to"
                :to="item.to"
                class="flex min-h-11 items-center gap-3 border-l-2 px-3 text-sm font-semibold transition-colors"
                :class="isActive(item.to)
                  ? 'border-action bg-action-soft text-ink'
                  : 'border-transparent text-ink-muted hover:bg-surface-2 hover:text-ink'"
                :aria-current="isActive(item.to) ? 'page' : undefined"
              >
                <Icon :name="item.icon" class="size-5 shrink-0" aria-hidden="true" />
                <span>{{ item.label }}</span>
              </NuxtLink>
            </div>
          </div>

          <div v-if="auth.isAdmin" class="border-t border-border pt-3">
            <NuxtLink
              :to="adminNavItem.to"
              class="flex min-h-11 items-center gap-3 border-l-2 px-3 text-sm font-semibold transition-colors"
              :class="isActive(adminNavItem.to)
                ? 'border-action bg-action-soft text-ink'
                : 'border-transparent text-ink-muted hover:bg-surface-2 hover:text-ink'"
              :aria-current="isActive(adminNavItem.to) ? 'page' : undefined"
            >
              <Icon :name="adminNavItem.icon" class="size-5 shrink-0" aria-hidden="true" />
              <span>{{ adminNavItem.label }}</span>
            </NuxtLink>
          </div>
        </nav>
      </UiSheet>

      <AppOfflineBanner />
      <main class="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        <slot />
      </main>
    </div>
  </div>
</template>
