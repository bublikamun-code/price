<script setup lang="ts">
// Баннерная карточка главной: «Акции» / «Новинки» (SITEMAP `/`, §16 баннеры).
// Приоритет: активный баннер из GET /api/v1/banners?position=...; если баннера нет —
// запасной товар из каруселей дашборда (fallback). Нет ни того ни другого — не рендерится.
import type { BannerRead } from '~/types/api'

// Товар-заглушка (шейп ClientNewArrival из GET /api/v1/dashboard).
interface FallbackItem {
  id: string
  sku: string
  name: string
  photo_key: string | null
  client_price: string
  currency: string
  has_discount: boolean
}

const props = defineProps<{
  title: string
  icon: string
  banners: BannerRead[]
  fallback: FallbackItem | null
  fallbackHref: string
}>()

const { urlOf, thumbOf } = useProductPhoto()

// Первый активный баннер списка (API отдаёт уже отсортированные, sort ASC).
const banner = computed(() => props.banners[0] ?? null)

// Ссылка баннера: товар → /catalog/{sku}, новость → /news/{id}; NONE — без ссылки.
const bannerHref = computed(() => {
  const b = banner.value
  if (!b) return null
  if (b.link_type === 'PRODUCT' && b.link_value) return `/catalog/${b.link_value}`
  if (b.link_type === 'NEWS' && b.link_value) return `/news/${b.link_value}`
  return null
})

// Показываем карточку, только если есть хоть что-то.
const visible = computed(() => banner.value !== null || props.fallback !== null)
</script>

<template>
  <NuxtLink
    v-if="visible && bannerHref"
    :to="bannerHref"
    class="border border-border bg-surface overflow-hidden flex flex-col transition-colors hover:bg-surface-2"
  >
    <div class="flex items-center justify-between gap-2 px-5 py-4">
      <h3 class="font-semibold flex items-center gap-2 min-w-0">
        <Icon :name="icon" class="w-5 h-5 shrink-0 text-primary" />
        <span class="truncate">{{ title }}</span>
      </h3>
      <Icon name="heroicons:arrow-right" class="w-5 h-5 shrink-0 text-ink-faint" />
    </div>

    <!-- Фото только на десктопе; на мобильном карточка короткая — заголовок + текст -->
    <div class="hidden lg:block aspect-auto lg:flex-1 lg:min-h-[160px] mx-5 mb-3 bg-surface-2 overflow-hidden border border-border">
      <img
        v-if="banner?.image_key"
        :src="urlOf(banner.image_key)"
        :alt="banner.title"
        class="w-full h-full object-contain no-dark-invert"
        loading="lazy"
      >
      <div v-else class="w-full h-full flex items-center justify-center">
        <Icon :name="icon" class="w-10 h-10 text-ink-faint" />
      </div>
    </div>

    <div class="px-5 pb-5 min-w-0">
      <p class="font-semibold leading-snug mb-1">{{ banner!.title }}</p>
      <p v-if="banner!.subtitle" class="text-sm text-ink-muted leading-relaxed line-clamp-2">{{ banner!.subtitle }}</p>
    </div>
  </NuxtLink>

  <!-- Баннер без ссылки (link_type NONE) -->
  <div v-else-if="visible && banner" class="border border-border bg-surface overflow-hidden flex flex-col">
    <div class="flex items-center justify-between gap-2 px-5 py-4">
      <h3 class="font-semibold flex items-center gap-2 min-w-0">
        <Icon :name="icon" class="w-5 h-5 shrink-0 text-primary" />
        <span class="truncate">{{ title }}</span>
      </h3>
      <Icon name="heroicons:arrow-right" class="w-5 h-5 shrink-0 text-ink-faint" />
    </div>

    <div class="hidden lg:block aspect-auto lg:flex-1 lg:min-h-[160px] mx-5 mb-3 bg-surface-2 overflow-hidden border border-border">
      <img
        v-if="banner.image_key"
        :src="urlOf(banner.image_key)"
        :alt="banner.title"
        class="w-full h-full object-contain no-dark-invert"
        loading="lazy"
      >
      <div v-else class="w-full h-full flex items-center justify-center">
        <Icon :name="icon" class="w-10 h-10 text-ink-faint" />
      </div>
    </div>

    <div class="px-5 pb-5 min-w-0">
      <p class="font-semibold leading-snug mb-1">{{ banner.title }}</p>
      <p v-if="banner.subtitle" class="text-sm text-ink-muted leading-relaxed line-clamp-2">{{ banner.subtitle }}</p>
    </div>
  </div>

  <!-- Запасной товар из дашборда -->
  <NuxtLink
    v-else-if="fallback"
    :to="fallbackHref"
    class="border border-border bg-surface overflow-hidden flex flex-col transition-colors hover:bg-surface-2"
  >
    <div class="flex items-center justify-between gap-2 px-5 py-4">
      <h3 class="font-semibold flex items-center gap-2 min-w-0">
        <Icon :name="icon" class="w-5 h-5 shrink-0 text-primary" />
        <span class="truncate">{{ title }}</span>
      </h3>
      <Icon name="heroicons:arrow-right" class="w-5 h-5 shrink-0 text-ink-faint" />
    </div>

    <div class="hidden lg:block aspect-auto lg:flex-1 lg:min-h-[160px] mx-5 mb-3 bg-surface-2 overflow-hidden border border-border">
      <img
        v-if="thumbOf(fallback.photo_key)"
        :src="thumbOf(fallback.photo_key)!"
        :alt="fallback.name"
        class="w-full h-full object-contain"
        loading="lazy"
      >
      <div v-else class="w-full h-full flex items-center justify-center">
        <Icon name="heroicons:photo" class="w-10 h-10 text-ink-faint" />
      </div>
    </div>

    <div class="px-5 pb-5 min-w-0">
      <p class="font-semibold leading-snug mb-1 line-clamp-2">{{ fallback.name }}</p>
      <p class="text-sm font-bold text-primary">{{ formatMoney(fallback.client_price, fallback.currency) }}</p>
    </div>
  </NuxtLink>
</template>
