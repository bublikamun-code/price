<script setup lang="ts">
// Список новостей (SITEMAP `/news`). Публичная страница, layout по умолчанию —
// как /news/[id]. Данные: GET /api/v1/news → NewsPage { data, meta }
// (тот же эндпоинт, что на главной и в лендинге).
import type { NewsPage, NewsRead } from '~/types/api'

useHead({ title: 'Новости' })

const { request } = useApi()

const PER_PAGE = 12

const news = ref<NewsRead[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

/** Краткий текст: первые 160 символов контента, обрезанные по слову. */
function newsExcerpt(content: string): string {
  if (content.length <= 160) return content
  const cut = content.slice(0, 160)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 80 ? cut.slice(0, lastSpace) : cut) + '…'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<NewsPage>('/api/v1/news', {
      query: { page: page.value, per_page: PER_PAGE },
    })
    news.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить новости')
  } finally {
    loading.value = false
  }
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

onMounted(load)
</script>

<template>
  <div class="container-app py-8">
    <div class="max-w-5xl mx-auto">
      <h1 class="text-2xl sm:text-3xl font-bold mb-2">Новости</h1>
      <p class="text-sm text-ink-muted mb-8">
        Новинки ассортимента и обновления портала.
      </p>

      <!-- Ошибка + повтор -->
      <div v-if="error" class="flex flex-wrap items-center gap-3 mb-4">
        <div class="badge-danger">{{ error }}</div>
        <button type="button" class="btn-ghost text-sm" @click="load()">Повторить</button>
      </div>

      <!-- Skeleton -->
      <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5" aria-hidden="true">
        <div v-for="i in 6" :key="i" class="card p-5">
          <div class="skeleton h-3 w-1/3 mb-3" />
          <div class="skeleton h-5 w-full mb-2" />
          <div class="skeleton h-3 w-full mb-2" />
          <div class="skeleton h-3 w-2/3" />
        </div>
      </div>

      <!-- Пусто -->
      <EmptyState
        v-else-if="!news.length"
        icon="heroicons:newspaper"
        title="Новостей пока нет"
        description="Здесь появятся новинки ассортимента и обновления портала."
      />

      <!-- Карточки новостей -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        <NuxtLink v-for="item in news" :key="item.id" :to="`/news/${item.id}`">
          <article class="card card-hover p-5 h-full">
            <div class="flex items-center gap-2 mb-2">
              <span v-if="item.type === 'NEW_PRODUCT'" class="badge-success text-xs">Новинка</span>
              <span v-else class="badge-info text-xs">Новость</span>
              <time class="text-xs text-ink-muted" :datetime="item.published_at">{{ formatDate(item.published_at) }}</time>
            </div>
            <h2 class="font-semibold mb-2 leading-snug hover:text-primary transition-colors">{{ item.title }}</h2>
            <p class="text-sm text-ink-muted leading-relaxed">{{ newsExcerpt(item.content) }}</p>
          </article>
        </NuxtLink>
      </div>

      <!-- Пагинация -->
      <nav
        v-if="!loading && totalPages > 1"
        class="flex items-center justify-center gap-1 mt-8"
        aria-label="Постраничная навигация"
      >
        <button class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
          <Icon name="heroicons:chevron-left" class="w-5 h-5" />
        </button>
        <button
          v-for="pgn in totalPages"
          :key="pgn"
          class="w-10 h-10 rounded-pill font-medium text-sm"
          :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
          @click="goPage(pgn)"
        >{{ pgn }}</button>
        <button class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
          <Icon name="heroicons:chevron-right" class="w-5 h-5" />
        </button>
      </nav>
    </div>
  </div>
</template>
