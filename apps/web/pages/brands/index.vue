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
  <div class="container-app py-8 lg:py-12">
    <PageHeading
      eyebrow="Публичный каталог"
      title="Каталоги брендов"
      description="Состав склада открыт: выберите бренд и посмотрите серии с номенклатурой."
    />

    <div v-if="status === 'pending'" class="record-list mt-8" aria-busy="true">
      <div v-for="i in 6" :key="i" class="record flex items-center gap-4">
        <UiSkeleton class="size-12 shrink-0" />
        <div class="min-w-0 flex-1">
          <UiSkeleton class="h-4 w-2/5" />
          <UiSkeleton class="mt-2 h-3 w-1/3" />
        </div>
      </div>
    </div>

    <UiErrorState
      v-else-if="error"
      class="mt-8"
      title="Не удалось загрузить бренды"
      :description="getErrorMessage(error, 'Проверьте соединение и повторите попытку.', { nested: true })"
      @retry="refresh"
    />

    <UiPanel v-else-if="!brands?.length" class="mt-8">
      <UiEmptyState
        icon="heroicons:squares-2x2"
        title="Скоро здесь появятся каталоги"
        description="Мы уже готовим витрину — загляните позже."
      />
    </UiPanel>

    <template v-else>
      <nav class="record-list mt-8" aria-label="Бренды">
        <NuxtLink
          v-for="b in brands"
          :key="b.id"
          :to="`/brands/${encodeURIComponent(b.slug)}`"
          class="record flex min-h-20 items-center gap-4 hover:bg-surface-2"
        >
          <span class="flex size-12 shrink-0 items-center justify-center border border-border bg-surface-2 text-lg font-bold text-ink">
            {{ initialOf(b.name) }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate font-semibold text-ink">{{ b.name }}</span>
            <span class="mt-1 block text-xs text-ink-muted">Серии и номенклатура</span>
          </span>
          <Icon name="heroicons:chevron-right" class="size-5 shrink-0 text-ink-muted" aria-hidden="true" />
        </NuxtLink>
      </nav>

      <section class="mt-10 max-w-4xl border-t border-border pt-6">
        <h2 class="text-lg font-semibold">О каталогах</h2>
        <p class="mt-3 text-sm leading-6 text-ink-muted">
          Мы публикуем состав каталогов открыто: по каждому бренду доступны серии, наименования и артикулы.
          Персональные цены со скидками по вашему договору, остатки и оформление заявок доступны после входа
          в личный кабинет — данные выдаёт ваш персональный менеджер.
        </p>
      </section>
    </template>

    <section class="mt-10 flex flex-col items-start justify-between gap-4 border-y border-border bg-surface px-5 py-6 sm:flex-row sm:items-center">
      <div>
        <h2 class="text-lg font-semibold">Войдите, чтобы увидеть цены</h2>
        <p class="mt-1 text-sm text-ink-muted">Персональный прайс-лист, корзина и заявки — в вашем кабинете.</p>
      </div>
      <NuxtLink to="/login" class="btn-primary shrink-0">Войти в кабинет</NuxtLink>
    </section>
  </div>
</template>
