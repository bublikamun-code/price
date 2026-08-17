<script setup lang="ts">
// Файловый архив (клиент). См. SITEMAP.md `/files`, ARCHITECTURE_PLAN.md §6, §16 п.18.
// Реальные данные: GET /api/v1/files (клиент видит PUBLIC/AUTHED),
// GET /api/v1/files/{id}/download → presigned URL (5 мин). Бренды для фильтра — /catalog/filters.
import type {
  BrandRef,
  FileAsset,
  FileAssetPage,
  FileAssetType,
  FileDownloadOut,
  FiltersOut,
} from '~/types/api'

definePageMeta({ layout: 'client', middleware: ['auth'] })
useHead({ title: 'Файлы' })

const { request } = useApi()

const PER_PAGE = 10

// Метки типов файлов (badge в таблице).
const TYPE_META: Record<string, { label: string }> = {
  BRAND_PDF: { label: 'PDF-каталог' },
  CUSTOM_CSV: { label: 'CSV-выгрузка' },
  PHOTO_ZIP: { label: 'Фото-архив' },
  OTHER: { label: 'Прочее' },
}

// --- Состояние списка ---
const files = ref<FileAsset[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')

const typeFilter = ref<'' | FileAssetType>('')
const brandFilter = ref('')
const brands = ref<BrandRef[]>([])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<FileAssetPage>('/api/v1/files', {
      query: {
        type: typeFilter.value || undefined,
        brand_id: brandFilter.value || undefined,
        page: page.value,
        per_page: PER_PAGE,
      },
    })
    files.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить файлы')
  } finally {
    loading.value = false
  }
}

// Бренды для фильтра — тот же источник, что у каталога (GET /catalog/filters).
async function loadBrands() {
  try {
    const f = await request<FiltersOut>('/api/v1/catalog/filters')
    brands.value = f.brands
  } catch {
    // фильтр по бренду не критичен — оставляем пустым
  }
}

function applyFilters() {
  page.value = 1
  load()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// --- Скачивание: получить presigned URL → открыть в новой вкладке ---
const downloadingId = ref<string | null>(null)
const downloadError = ref('')

async function download(f: FileAsset) {
  if (downloadingId.value) return
  downloadingId.value = f.id
  downloadError.value = ''
  try {
    // Контракт §16 п.18: одиночный ответ обёрнут в {"data": ...}.
    const res = await request<FileDownloadOut & { data?: FileDownloadOut }>(
      `/api/v1/files/${f.id}/download`,
    )
    const link = res.data ?? res
    window.open(link.url, '_blank')
  } catch (e) {
    downloadError.value = getErrorMessage(e, 'Не удалось получить ссылку на файл')
  } finally {
    downloadingId.value = null
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function formatDate(s: string): string {
  return new Date(s).toLocaleString('ru-RU')
}

onMounted(() => {
  load()
  loadBrands()
})
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Файлы</h1>
      <p class="text-sm text-ink-muted mt-1">
        PDF-каталоги брендов и специальные выгрузки для скачивания.
      </p>
    </div>

    <!-- Фильтры -->
    <div class="flex flex-col sm:flex-row gap-4 mb-6">
      <div class="sm:w-64">
        <label class="label" for="type">Тип</label>
        <select id="type" v-model="typeFilter" class="input py-2.5" @change="applyFilters">
          <option value="">Все файлы</option>
          <option value="BRAND_PDF">PDF-каталог бренда</option>
          <option value="CUSTOM_CSV">Спец-выгрузка CSV</option>
          <option value="OTHER">Прочее</option>
        </select>
      </div>
      <div v-if="brands.length" class="sm:w-64">
        <label class="label" for="brand">Бренд</label>
        <select id="brand" v-model="brandFilter" class="input py-2.5" @change="applyFilters">
          <option value="">Все бренды</option>
          <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load()">Повторить</button>
    </div>
    <div v-if="downloadError" class="badge-danger w-full justify-center py-2 mb-4">
      {{ downloadError }}
    </div>

    <!-- Скелетоны -->
    <div v-if="loading" class="card p-5">
      <div v-for="i in 4" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <!-- Пусто -->
    <div v-else-if="!files.length" class="card p-10 text-center text-ink-muted">
      <Icon name="heroicons:folder" class="w-10 h-10 mx-auto mb-3 text-ink-faint" />
      <p>Файлов пока нет</p>
    </div>

    <!-- Таблица -->
    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-canvas">
              <th class="px-4 py-3 font-medium">Имя</th>
              <th class="px-4 py-3 font-medium">Тип</th>
              <th class="px-4 py-3 font-medium">Бренд</th>
              <th class="px-4 py-3 font-medium">Размер</th>
              <th class="px-4 py-3 font-medium">Дата</th>
              <th class="px-4 py-3 font-medium text-right">Действие</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in files"
              :key="f.id"
              class="border-t border-border hover:bg-canvas/60"
            >
              <td class="px-4 py-3 max-w-[240px] truncate" :title="f.filename">{{ f.filename }}</td>
              <td class="px-4 py-3">
                <span class="badge-info">{{ TYPE_META[f.type]?.label || f.type }}</span>
              </td>
              <td class="px-4 py-3 text-ink-muted">{{ f.brand_name || '—' }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatSize(f.size_bytes) }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(f.created_at) }}</td>
              <td class="px-4 py-3 text-right">
                <button
                  class="btn-ghost text-sm py-1.5"
                  :disabled="downloadingId === f.id"
                  @click="download(f)"
                >
                  <span
                    v-if="downloadingId === f.id"
                    class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"
                  />
                  <Icon v-else name="heroicons:arrow-down-tray" class="w-4 h-4" />
                  Скачать
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Пагинация -->
    <nav v-if="!loading && totalPages > 1" class="flex items-center justify-center gap-1 mt-6">
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
</template>
