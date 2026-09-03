<script setup lang="ts">
// Публичная SEO-витрина брендов (SITEMAP §5; §16 п.29). Без цен/остатков/ПДн.
// GET /api/v1/public/brands — ответ может быть в конверте {data: …} (§6).
import type { PublicBrand } from '~/types/api'

useSeoMeta({
  title: 'Каталоги брендов',
  description: 'Открытые каталоги брендов: серии и номенклатура каждого бренда. Персональные цены по договору доступны после входа в личный кабинет.',
  ogTitle: 'Каталоги брендов',
  ogDescription: 'Серии и номенклатура брендов B2B-портала. Персональные цены — после входа в личный кабинет.',
  ogType: 'website',
})

const { $api: fetchJson } = useNuxtApp()

const { data: brands, status, error, refresh } = useAsyncData('public-brands', async () =>
  unwrapData<PublicBrand[]>(await fetchJson('/api/v1/public/brands')),
)

function initialOf(name: string): string {
  return name.charAt(0).toUpperCase()
}
</script>

<template>
  <div class="container-app py-10 lg:py-14">
    <div class="max-w-2xl mb-8">
      <span class="chip bg-surface-2 text-primary mb-4">Публичный каталог</span>
      <h1 class="text-3xl sm:text-4xl font-bold mb-3">Каталоги брендов</h1>
      <p class="text-lg text-ink-muted">
        Состав склада открыт: выберите бренд и посмотрите серии с номенклатурой.
      </p>
    </div>

    <!-- Skeleton -->
    <div v-if="status === 'pending'" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      <div v-for="i in 8" :key="i" class="card p-5">
        <div class="skeleton w-12 h-12 rounded-pill mb-4" />
        <div class="skeleton h-4 w-3/4" />
      </div>
    </div>

    <!-- Ошибка -->
    <div v-else-if="error" class="card p-12 text-center">
      <Icon name="heroicons:exclamation-triangle" class="w-12 h-12 mx-auto mb-3 text-danger" />
      <p class="mb-5">{{ getErrorMessage(error, 'Не удалось загрузить бренды', { nested: true }) }}</p>
      <button class="btn-primary" @click="() => refresh()">Повторить</button>
    </div>

    <!-- Пусто -->
    <div v-else-if="!brands?.length" class="card p-12 text-center">
      <Icon name="heroicons:squares-2x2" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p class="mb-1 font-medium">Скоро здесь появятся каталоги</p>
      <p class="text-sm text-ink-muted">Мы уже готовим витрину — загляните позже.</p>
    </div>

    <!-- Список брендов -->
    <template v-else>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <NuxtLink
          v-for="b in brands"
          :key="b.id"
          :to="`/brands/${b.slug}`"
          class="card card-hover p-6 flex items-center gap-4"
        >
          <span class="shrink-0 w-12 h-12 rounded-pill bg-surface-2 text-secondary flex items-center justify-center text-lg font-bold">{{ initialOf(b.name) }}</span>
          <span class="min-w-0 flex-1">
            <span class="block font-semibold truncate">{{ b.name }}</span>
            <span class="block text-xs text-ink-faint mt-0.5">Серии и номенклатура</span>
          </span>
          <Icon name="heroicons:chevron-right" class="w-5 h-5 shrink-0 text-ink-faint" />
        </NuxtLink>
      </div>

      <section class="card p-6 sm:p-8 mt-8 max-w-4xl">
        <h2 class="text-lg font-semibold mb-3">О каталогах</h2>
        <p class="text-sm text-ink-muted leading-relaxed">
          Мы публикуем состав каталогов открыто: по каждому бренду доступны серии, наименования и артикулы.
          Персональные цены со скидками по вашему договору, остатки и оформление заявок доступны после входа
          в личный кабинет — данные выдаёт ваш персональный менеджер.
        </p>
      </section>
    </template>

    <!-- CTA -->
    <section class="mt-8">
      <div class="card border-primary/20 bg-surface-2 p-6 sm:p-8 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div class="text-center sm:text-left">
          <h2 class="text-lg font-semibold mb-1">Войдите, чтобы увидеть цены</h2>
          <p class="text-sm text-ink-muted">Персональный прайс-лист, корзина и заявки — в вашем кабинете.</p>
        </div>
        <NuxtLink to="/login" class="btn-primary px-6 py-3 shrink-0">Войти в кабинет</NuxtLink>
      </div>
    </section>
  </div>
</template>
