<script setup lang="ts">
// Публичная страница полной новости (SITEMAP `/news/[id]`).
// GET /api/v1/news/{id} → NewsRead. Без middleware — layout по умолчанию.
import type { NewsRead } from '~/types/api'

const route = useRoute()
const { request } = useApi()

const loading = ref(true)
const notFound = ref(false)
const error = ref('')
const article = ref<NewsRead | null>(null)

useHead({ title: 'Новость' })

// Контент хранится плоской строкой — режем на абзацы по пустым строкам.
const paragraphs = computed(() =>
  (article.value?.content || '')
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean),
)

async function load() {
  loading.value = true
  notFound.value = false
  error.value = ''
  try {
    article.value = await request<NewsRead>(`/api/v1/news/${encodeURIComponent(String(route.params.id))}`)
    useHead({ title: article.value.title })
  } catch (e) {
    if (getErrorStatus(e) === 404) {
      notFound.value = true
    } else {
      error.value = getErrorMessage(e, 'Не удалось загрузить новость')
    }
  } finally {
    loading.value = false
  }
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

onMounted(load)
</script>

<template>
  <div class="container-app py-8">
    <div class="max-w-3xl mx-auto">
      <button
        type="button"
        class="flex items-center gap-1.5 text-sm text-ink-muted hover:text-primary transition-colors mb-6"
        @click="$router.back()"
      >
        <Icon name="heroicons:arrow-left" class="w-4 h-4" /> Назад
      </button>

      <!-- Skeleton -->
      <div v-if="loading" aria-hidden="true">
        <div class="skeleton h-4 w-40 mb-4" />
        <div class="skeleton h-8 w-3/4 mb-6" />
        <div class="skeleton h-64 w-full rounded-card mb-6" />
        <div class="skeleton h-4 w-full mb-3" />
        <div class="skeleton h-4 w-full mb-3" />
        <div class="skeleton h-4 w-2/3" />
      </div>

      <!-- 404 -->
      <div v-else-if="notFound" class="card p-12 text-center">
        <Icon name="heroicons:newspaper" class="w-12 h-12 mx-auto mb-4 text-ink-faint" />
        <h1 class="text-xl font-bold mb-2">Новость не найдена</h1>
        <p class="text-sm text-ink-muted mb-6">Возможно, она была удалена или ссылка устарела.</p>
        <NuxtLink to="/" class="btn-primary">На главную</NuxtLink>
      </div>

      <!-- Ошибка -->
      <div v-else-if="error" class="card p-8 text-center">
        <div class="badge-danger mb-4 inline-flex">{{ error }}</div>
        <div>
          <button type="button" class="btn-primary" @click="load()">Повторить</button>
        </div>
      </div>

      <!-- Статья -->
      <article v-else-if="article">
        <div class="flex items-center gap-2 mb-3">
          <span v-if="article.type === 'NEW_PRODUCT'" class="badge-success">Новинка</span>
          <span v-else class="badge-info">Новость</span>
          <time class="text-sm text-ink-muted" :datetime="article.published_at">{{ formatDate(article.published_at) }}</time>
        </div>

        <h1 class="text-2xl sm:text-3xl font-bold mb-6 leading-tight">{{ article.title }}</h1>

        <img
          v-if="article.image_url"
          :src="article.image_url"
          :alt="article.title"
          class="w-full rounded-card mb-6 border border-border"
          loading="lazy"
        >

        <div class="text-base">
          <p v-for="(p, i) in paragraphs" :key="i" class="mb-4 leading-relaxed text-ink-muted">{{ p }}</p>
        </div>
      </article>
    </div>
  </div>
</template>
