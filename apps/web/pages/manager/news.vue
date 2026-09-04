<script setup lang="ts">
// Новостная лента (менеджер). CRUD: /api/v1/manager/news.
// Список — ВСЕ записи (включая скрытые), конверт NewsPage.
import type { NewsPage, NewsRead, NewsType } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Новости — Менеджер' })

const { request } = useApi()

// Менеджерский список дополнительно отдаёт флаг активности.
interface ManagerNewsRead extends NewsRead {
  is_active?: boolean
}

const PER_PAGE = 10

const TYPE_META: Record<NewsType, { label: string; cls: string }> = {
  NEWS: { label: 'Новость', cls: 'badge-info' },
  NEW_PRODUCT: { label: 'Новинка', cls: 'badge-success' },
}

// --- Список ---
const news = ref<ManagerNewsRead[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<NewsPage>('/api/v1/manager/news', {
      query: { page: page.value, per_page: PER_PAGE },
    })
    news.value = res.data as ManagerNewsRead[]
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить список новостей')
  } finally {
    loading.value = false
  }
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

function formatDate(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}

// ISO → value формата datetime-local (yyyy-MM-ddThh:mm) для редактирования.
function toLocalInput(s: string): string {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// --- Модалка создания/редактирования ---
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const submitError = ref('')

interface NewsForm {
  title: string
  type: NewsType
  content: string
  image_url: string
  published_at: string // datetime-local или пусто = сейчас
  is_active: boolean
}

const emptyForm = (): NewsForm => ({
  title: '',
  type: 'NEWS',
  content: '',
  image_url: '',
  published_at: '',
  is_active: true,
})

const form = ref<NewsForm>(emptyForm())

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  submitError.value = ''
  modalOpen.value = true
}

function openEdit(n: ManagerNewsRead) {
  editingId.value = n.id
  form.value = {
    title: n.title,
    type: n.type,
    content: n.content,
    image_url: n.image_url ?? '',
    published_at: toLocalInput(n.published_at),
    is_active: n.is_active ?? true,
  }
  submitError.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false
}

async function onSubmit() {
  submitError.value = ''
  if (!form.value.title.trim()) {
    submitError.value = 'Укажите заголовок'
    return
  }
  if (!form.value.content.trim()) {
    submitError.value = 'Укажите текст статьи'
    return
  }
  const body: Record<string, unknown> = {
    title: form.value.title.trim(),
    type: form.value.type,
    content: form.value.content,
    image_url: form.value.image_url.trim() || null,
    published_at: form.value.published_at ? new Date(form.value.published_at).toISOString() : null,
    is_active: form.value.is_active,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await request(`/api/v1/manager/news/${editingId.value}`, { method: 'PATCH', body })
    } else {
      await request('/api/v1/manager/news', { method: 'POST', body })
    }
    modalOpen.value = false
    await load()
  } catch (e) {
    submitError.value = getErrorMessage(e, 'Не удалось сохранить новость')
  } finally {
    submitting.value = false
  }
}

// --- Скрыть/показать, удалить ---
const busyId = ref<string | null>(null)

async function toggleActive(n: ManagerNewsRead) {
  busyId.value = n.id
  error.value = ''
  try {
    await request(`/api/v1/manager/news/${n.id}`, { method: 'PATCH', body: { is_active: !(n.is_active ?? true) } })
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось изменить новость')
  } finally {
    busyId.value = null
  }
}

async function remove(n: ManagerNewsRead) {
  if (!window.confirm(`Удалить новость «${n.title}»? Действие необратимо.`)) return
  busyId.value = n.id
  error.value = ''
  try {
    await request(`/api/v1/manager/news/${n.id}`, { method: 'DELETE' })
    if (news.value.length === 1 && page.value > 1) page.value--
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось удалить новость')
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex items-start justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Новости</h1>
        <p class="text-sm text-ink-muted mt-1">
          Лента «Новости и обновления» на главной. Скрытые записи клиентам не показываются.
        </p>
      </div>
      <button type="button" class="btn-primary whitespace-nowrap" @click="openCreate">
        <Icon name="heroicons:plus" class="w-4 h-4" /> Добавить
      </button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button type="button" class="btn-ghost text-sm" @click="load()">Повторить</button>
    </div>

    <!-- Скелетоны -->
    <div v-if="loading" class="card p-5">
      <div v-for="i in 3" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0" />
    </div>

    <!-- Пусто -->
    <div v-else-if="!news.length" class="card p-10 text-center text-ink-muted">
      <Icon name="heroicons:newspaper" class="w-10 h-10 mx-auto mb-3 text-ink-faint" />
      <p>Новостей пока нет</p>
    </div>

    <!-- Таблица -->
    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Заголовок</th>
              <th class="px-4 py-3 font-medium">Тип</th>
              <th class="px-4 py-3 font-medium">Дата публикации</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="n in news" :key="n.id" class="border-t border-border hover:bg-canvas/60">
              <td class="px-4 py-3 max-w-[320px] truncate font-medium" :title="n.title">{{ n.title }}</td>
              <td class="px-4 py-3">
                <span :class="TYPE_META[n.type]?.cls || 'badge-info'">{{ TYPE_META[n.type]?.label || n.type }}</span>
              </td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(n.published_at) }}</td>
              <td class="px-4 py-3">
                <span :class="(n.is_active ?? true) ? 'badge-success' : 'badge-warning'">
                  {{ (n.is_active ?? true) ? 'Видна' : 'Скрыта' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <button type="button" class="btn-ghost text-sm py-1.5" :disabled="busyId === n.id" @click="openEdit(n)">
                  <Icon name="heroicons:pencil-square" class="w-4 h-4" /> Изменить
                </button>
                <button type="button" class="btn-ghost text-sm py-1.5" :disabled="busyId === n.id" @click="toggleActive(n)">
                  {{ (n.is_active ?? true) ? 'Скрыть' : 'Показать' }}
                </button>
                <button
                  type="button"
                  class="btn-ghost text-sm py-1.5 text-danger"
                  :disabled="busyId === n.id"
                  @click="remove(n)"
                >
                  <span
                    v-if="busyId === n.id"
                    class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"
                  />
                  <template v-else>
                    <Icon name="heroicons:trash" class="w-4 h-4" /> Удалить
                  </template>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Пагинация -->
    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
      <button type="button" class="btn-ghost p-2.5" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <button
        v-for="pgn in totalPages"
        :key="pgn"
        type="button"
        class="w-10 h-10 rounded-pill font-medium text-sm"
        :class="pgn === page ? 'bg-primary text-white' : 'text-ink-muted hover:bg-canvas'"
        @click="goPage(pgn)"
      >{{ pgn }}</button>
      <button type="button" class="btn-ghost p-2.5" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>

    <!-- Модалка -->
    <div v-if="modalOpen" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" @click.self="closeModal">
      <div class="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">
        <div class="flex items-center justify-between gap-3 mb-5">
          <h2 class="text-lg font-semibold">{{ editingId ? 'Изменить новость' : 'Новая новость' }}</h2>
          <button type="button" class="btn-ghost p-1.5" aria-label="Закрыть" @click="closeModal">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <form class="grid grid-cols-1 sm:grid-cols-2 gap-4" @submit.prevent="onSubmit">
          <div class="sm:col-span-2">
            <label class="label" for="news-title">Заголовок</label>
            <input id="news-title" v-model="form.title" type="text" class="input py-2.5" required>
          </div>

          <div>
            <label class="label" for="news-type">Тип</label>
            <select id="news-type" v-model="form.type" class="input py-2.5">
              <option value="NEWS">Новость</option>
              <option value="NEW_PRODUCT">Новинка</option>
            </select>
          </div>

          <div>
            <label class="label" for="news-published">Дата публикации</label>
            <input id="news-published" v-model="form.published_at" type="datetime-local" class="input py-2.5">
            <p class="text-xs text-ink-faint mt-1.5">Пусто — опубликовать сейчас</p>
          </div>

          <div class="sm:col-span-2">
            <label class="label" for="news-content">Текст статьи</label>
            <textarea id="news-content" v-model="form.content" rows="12" class="input py-2.5" required />
            <p class="text-xs text-ink-faint mt-1.5">Абзацы разделяются пустыми строками</p>
          </div>

          <div class="sm:col-span-2">
            <label class="label" for="news-image">URL изображения</label>
            <input id="news-image" v-model="form.image_url" type="text" class="input py-2.5" placeholder="https://…">
            <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
          </div>

          <div class="sm:col-span-2 flex items-center gap-2">
            <input id="news-active" v-model="form.is_active" type="checkbox" class="w-4 h-4 accent-primary">
            <label for="news-active" class="text-sm font-medium">Показывать</label>
          </div>

          <div v-if="submitError" class="sm:col-span-2 badge-danger w-full justify-center py-2">{{ submitError }}</div>

          <div class="sm:col-span-2 flex justify-end gap-3">
            <button type="button" class="btn-ghost" @click="closeModal">Отмена</button>
            <button type="submit" class="btn-primary" :disabled="submitting">
              <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              {{ submitting ? 'Сохранение…' : 'Сохранить' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
