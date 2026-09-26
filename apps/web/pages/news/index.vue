<script setup lang="ts">
import type { NewsPage, NewsRead } from '~/types/api'

useSeoMeta({
  title: 'Новости',
  description: 'Новинки ассортимента и обновления портала.',
  ogTitle: 'Новости портала',
  ogDescription: 'Новинки ассортимента и обновления портала.',
  ogType: 'website',
})

const PER_PAGE = 12
const page = ref(1)
const { request } = useApi()

const { data: newsPage, status, error, refresh } = await useAsyncData<NewsPage>(
  'public-news',
  () => request<NewsPage>('/api/v1/news', {
    query: { page: page.value, per_page: PER_PAGE },
  }),
  { watch: [page] },
)

const news = computed<NewsRead[]>(() => newsPage.value?.data ?? [])
const total = computed(() => newsPage.value?.meta.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))
const errorMessage = computed(() => error.value
  ? getErrorMessage(error.value, 'Не удалось загрузить новости', { nested: true })
  : '')

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

function newsExcerpt(content: string): string {
  if (content.length <= 160) return content
  const cut = content.slice(0, 160)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 80 ? cut.slice(0, lastSpace) : cut) + '…'
}

function goPage(nextPage: number): void {
  page.value = Math.min(Math.max(nextPage, 1), totalPages.value)
}
</script>

<template>
  <div class="container-app py-8 lg:py-12">
    <div class="mx-auto max-w-5xl">
      <PageHeading
        eyebrow="Публичные материалы"
        title="Новости"
        description="Новинки ассортимента и обновления портала."
      />

      <UiErrorState
        v-if="errorMessage"
        class="mb-6"
        title="Не удалось загрузить новости"
        :description="errorMessage"
        @retry="refresh"
      />

      <div v-if="status === 'pending'" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
        <UiPanel v-for="i in 6" :key="i" class="min-h-48 p-5">
          <div class="skeleton h-3 w-1/3" />
          <div class="skeleton mt-4 h-5 w-full" />
          <div class="skeleton mt-3 h-3 w-full" />
          <div class="skeleton mt-2 h-3 w-2/3" />
        </UiPanel>
      </div>

      <UiPanel v-else-if="!news.length" class="mt-6">
        <UiEmptyState
          icon="heroicons:newspaper"
          title="Новостей пока нет"
          description="Здесь появятся новинки ассортимента и обновления портала."
        />
      </UiPanel>

      <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <NuxtLink
          v-for="item in news"
          :key="item.id"
          :to="`/news/${encodeURIComponent(item.id)}`"
          class="group"
        >
          <article class="record flex min-h-48 flex-col p-5 transition-colors hover:bg-surface-2">
            <div class="mb-3 flex items-center gap-2">
              <span v-if="item.type === 'NEW_PRODUCT'" class="badge-success">Новинка</span>
              <span v-else class="badge-info">Новость</span>
              <time class="text-xs text-ink-muted" :datetime="item.published_at">{{ formatDate(item.published_at) }}</time>
            </div>
            <h2 class="font-semibold leading-snug text-ink group-hover:text-action">{{ item.title }}</h2>
            <p class="mt-2 text-sm leading-6 text-ink-muted">{{ newsExcerpt(item.content) }}</p>
          </article>
        </NuxtLink>
      </div>

      <UiPagination
        v-if="status !== 'pending' && totalPages > 1"
        class="mt-8"
        :page="page"
        :page-count="totalPages"
        :total="total"
        label="Страницы новостей"
        @update:page="goPage"
      />
    </div>
  </div>
</template>
