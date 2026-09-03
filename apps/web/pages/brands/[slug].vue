<script setup lang="ts">
// Публичная страница бренда (SITEMAP §5; §16 п.29): серии + номенклатура без цен.
// GET /api/v1/public/brands/{slug} и /api/v1/public/series/{slug}/products.
import type { PublicBrandDetail, PublicSeriesProduct, PublicSeriesRef } from '~/types/api'

const route = useRoute()
const slug = computed(() => String(route.params.slug ?? ''))

const { $api: fetchJson } = useNuxtApp()

interface SeriesWithProducts extends PublicSeriesRef {
  products: PublicSeriesProduct[]
}

interface BrandDetail extends PublicBrandDetail {
  series: SeriesWithProducts[]
}

const { data: brand, status, error, refresh } = useAsyncData('public-brand', async () => {
  const raw = await fetchJson(`/api/v1/public/brands/${encodeURIComponent(slug.value)}`)
  const detail = unwrapData<PublicBrandDetail>(raw)
  const series = await Promise.all(
    (detail.series ?? []).map(async (s) => {
      try {
        const pr = await fetchJson(`/api/v1/public/series/${encodeURIComponent(s.slug)}/products?page=1&page_size=200`)
        return { ...s, products: unwrapData<PublicSeriesProduct[]>(pr) }
      } catch {
        return { ...s, products: [] }
      }
    }),
  )
  return { ...detail, series } as BrandDetail
}, { watch: [slug] })

if (getErrorStatus(error.value) === 404) {
  throw createError({ statusCode: 404, statusMessage: 'Бренд не найден', fatal: true })
}

useSeoMeta({
  title: () => brand.value ? `${brand.value.name} — каталог серий и номенклатуры` : 'Бренд',
  description: () => brand.value
    ? `Каталог ${brand.value.name}: ${plural(brand.value.series.length, ['серия', 'серии', 'серий'])}, наименования и артикулы. Персональные цены доступны после входа в личный кабинет.`
    : 'Каталог бренда: серии и номенклатура B2B-портала.',
  ogTitle: () => brand.value ? `${brand.value.name} — каталог серий и номенклатуры` : 'Каталог бренда',
  ogDescription: () => brand.value
    ? `Серии и номенклатура бренда ${brand.value.name}. Персональные цены — после входа в кабинет.`
    : 'Серии и номенклатура бренда на B2B-портале.',
  ogType: 'website',
})

function thumbUrl(key: string): string {
  return `/api/v1/public/photo?key=${encodeURIComponent(key)}`
}

function plural(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return `${n} ${forms[0]}`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} ${forms[1]}`
  return `${n} ${forms[2]}`
}
</script>

<template>
  <div class="container-app py-8 lg:py-12">
    <!-- Хлебные крошки -->
    <nav aria-label="Хлебные крошки" class="mb-6">
      <ol class="flex items-center flex-wrap gap-1.5 text-sm text-ink-muted">
        <li><NuxtLink to="/" class="hover:text-primary">Главная</NuxtLink></li>
        <li aria-hidden="true"><Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint" /></li>
        <li><NuxtLink to="/brands" class="hover:text-primary">Бренды</NuxtLink></li>
        <li aria-hidden="true"><Icon name="heroicons:chevron-right" class="w-4 h-4 text-ink-faint" /></li>
        <li>
          <span v-if="brand" class="text-ink font-medium">{{ brand.name }}</span>
          <span v-else>Бренд</span>
        </li>
      </ol>
    </nav>

    <!-- Skeleton -->
    <div v-if="status === 'pending'">
      <div class="skeleton h-9 w-64 mb-8" />
      <div v-for="i in 2" :key="i" class="mb-8">
        <div class="skeleton h-16 w-full rounded-card mb-3" />
        <div class="card divide-y divide-border">
          <div v-for="j in 4" :key="j" class="px-5 py-3">
            <div class="skeleton h-4 w-2/3" />
          </div>
        </div>
      </div>
    </div>

    <!-- Ошибка -->
    <div v-else-if="error" class="card p-12 text-center max-w-lg mx-auto">
      <Icon name="heroicons:exclamation-triangle" class="w-12 h-12 mx-auto mb-3 text-danger" />
      <p class="font-medium mb-1">Не удалось загрузить бренд</p>
      <p class="text-sm text-ink-muted mb-5">{{ getErrorMessage(error, 'Попробуйте позже', { nested: true }) }}</p>
      <button class="btn-primary" @click="() => refresh()">Повторить</button>
    </div>

    <!-- Нет серий -->
    <div v-else-if="!brand || !brand.series.length" class="card p-12 text-center max-w-lg mx-auto">
      <p class="text-6xl font-bold text-primary mb-3">404</p>
      <h1 class="text-xl font-semibold mb-2">Бренд не найден</h1>
      <p class="text-sm text-ink-muted mb-6">Возможно, каталог этого бренда ещё не опубликован.</p>
      <NuxtLink to="/brands" class="btn-primary">Все бренды</NuxtLink>
    </div>

    <!-- Серии с номенклатурой -->
    <template v-else>
      <header class="flex items-center gap-4 mb-10">
        <span class="shrink-0 w-14 h-14 rounded-pill bg-surface-2 text-secondary flex items-center justify-center text-xl font-bold">{{ brand.name.charAt(0).toUpperCase() }}</span>
        <div>
          <h1 class="text-3xl sm:text-4xl font-bold leading-tight">{{ brand.name }}</h1>
          <p class="text-sm text-ink-muted mt-1">{{ plural(brand.series.length, ['серия', 'серии', 'серий']) }} с номенклатурой</p>
        </div>
      </header>

      <section v-for="s in brand.series" :id="`series-${s.slug}`" :key="s.slug" class="mb-10 scroll-mt-24">
        <div class="flex items-center gap-4 mb-4">
          <span class="shrink-0 w-16 h-16 rounded-card bg-canvas border border-border/60 overflow-hidden flex items-center justify-center">
            <img
              v-if="s.photo_thumb"
              :src="thumbUrl(s.photo_thumb)"
              :alt="s.name"
              loading="lazy"
              class="w-full h-full object-contain"
            >
            <span v-else class="text-lg font-bold text-ink-faint">{{ s.name.charAt(0).toUpperCase() }}</span>
          </span>
          <div class="min-w-0">
            <h2 class="text-xl font-semibold truncate">{{ s.name }}</h2>
            <p class="text-xs text-ink-faint mt-0.5">
              {{ s.products.length ? plural(s.products.length, ['позиция', 'позиции', 'позиций']) : 'Номенклатура уточняется' }}
            </p>
          </div>
        </div>

        <ul class="card divide-y divide-border overflow-hidden">
          <li v-for="p in s.products" :key="p.sku" class="px-5 py-3 flex items-baseline gap-3">
            <span class="badge bg-canvas text-ink-muted font-mono shrink-0">{{ p.sku }}</span>
            <span class="text-sm min-w-0">{{ p.name }}</span>
          </li>
          <li v-if="!s.products.length" class="px-5 py-4 text-sm text-ink-muted">
            Товары этой серии скоро появятся в каталоге.
          </li>
        </ul>
      </section>

      <!-- CTA -->
      <section>
        <div class="card border-primary/20 bg-surface-2 p-6 sm:p-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div class="text-center sm:text-left">
            <h2 class="text-lg font-semibold mb-1">Цены доступны после входа</h2>
            <p class="text-sm text-ink-muted">Персональный прайс по вашему договору, остатки и заказ — в кабинете.</p>
          </div>
          <NuxtLink to="/login" class="btn-primary px-6 py-3 shrink-0">Войти в кабинет</NuxtLink>
        </div>
      </section>
    </template>
  </div>
</template>
