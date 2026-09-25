<script setup lang="ts">
import type { NewsRead } from '~/types/api'

const route = useRoute()
const { request } = useApi()
const articleId = computed(() => String(route.params.id ?? ''))

const { data: article, status, error, refresh } = await useAsyncData<NewsRead>(
  () => `public-news-${articleId.value}`,
  () => request<NewsRead>(`/api/v1/news/${encodeURIComponent(articleId.value)}`),
  { watch: [articleId] },
)

if (getErrorStatus(error.value) === 404) {
  throw createError({ statusCode: 404, statusMessage: 'Новость не найдена', fatal: true })
}

useSeoMeta({
  title: () => article.value?.title || 'Новость',
  description: () => article.value?.content?.slice(0, 160) || 'Новости портала.',
  ogTitle: () => article.value?.title || 'Новость',
  ogDescription: () => article.value?.content?.slice(0, 160) || 'Новости портала.',
  ogType: 'article',
})

const paragraphs = computed(() =>
  (article.value?.content || '')
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean),
)

const errorMessage = computed(() => error.value
  ? getErrorMessage(error.value, 'Не удалось загрузить новость', { nested: true })
  : '')

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}
</script>

<template>
  <div class="container-app py-8 lg:py-12">
    <div class="mx-auto max-w-3xl">
      <button
        type="button"
        class="mb-6 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-ink-muted transition-colors hover:text-action"
        @click="$router.back()"
      >
        <Icon name="heroicons:arrow-left" class="size-4" aria-hidden="true" />
        Назад
      </button>

      <div v-if="status === 'pending'" aria-busy="true">
        <UiLoadingState label="Загрузка новости" />
        <div class="skeleton mt-6 h-64 w-full" />
        <div class="skeleton mt-6 h-4 w-full" />
        <div class="skeleton mt-2 h-4 w-full" />
        <div class="skeleton mt-2 h-4 w-2/3" />
      </div>

      <UiErrorState
        v-else-if="errorMessage"
        title="Не удалось загрузить новость"
        :description="errorMessage"
        @retry="refresh"
      />

      <article v-else-if="article">
        <div class="mb-3 flex items-center gap-2">
          <span v-if="article.type === 'NEW_PRODUCT'" class="badge-success">Новинка</span>
          <span v-else class="badge-info">Новость</span>
          <time class="text-sm text-ink-muted" :datetime="article.published_at">{{ formatDate(article.published_at) }}</time>
        </div>

        <PageHeading :title="article.title" />

        <img
          v-if="article.image_url"
          :src="article.image_url"
          :alt="article.title"
          class="mb-8 w-full border border-border"
          loading="lazy"
        >

        <div class="prose-trade max-w-none text-base">
          <p v-for="(paragraph, index) in paragraphs" :key="index" class="mb-4 leading-7 text-ink-muted">
            {{ paragraph }}
          </p>
        </div>
      </article>
    </div>
  </div>
</template>
