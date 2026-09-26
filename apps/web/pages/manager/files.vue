<script setup lang="ts">
// Файловый архив (менеджер). См. SITEMAP.md `/manager/files`, ARCHITECTURE_PLAN.md §6, §16 п.18.
// Реальные данные: GET/POST/DELETE /api/v1/manager/files,
// GET /api/v1/files/{id}/download → presigned URL (5 мин). Бренды — /catalog/filters.
import type {
  BrandRef,
  FileAsset,
  FileAssetPage,
  FileAssetType,
  FileDownloadOut,
  FileVisibility,
  FiltersOut,
} from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Файлы — Менеджер' })

const { request } = useApi()

const PER_PAGE = 10
const MAX_SIZE = 200 * 1024 * 1024 // §16 п.18: лимит 200 МБ
const ALLOWED_EXT = ['.pdf', '.csv', '.zip']

// Метки типов файлов (badge + selects).
const TYPE_META: Record<string, { label: string }> = {
  BRAND_PDF: { label: 'PDF-каталог' },
  CUSTOM_CSV: { label: 'CSV-выгрузка' },
  PHOTO_ZIP: { label: 'Фото-архив' },
  OTHER: { label: 'Прочее' },
}

// UPLOAD_TYPES: PHOTO_ZIP системный (ставится загрузкой ZIP с фото, §16 п.17) — не загружается вручную.
const UPLOAD_TYPES: { value: FileAssetType; label: string }[] = [
  { value: 'BRAND_PDF', label: 'PDF-каталог бренда' },
  { value: 'CUSTOM_CSV', label: 'Спец-выгрузка CSV' },
  { value: 'OTHER', label: 'Прочее' },
]

const VISIBILITY_META: Record<string, { label: string; cls: string }> = {
  PUBLIC: { label: 'Открытый', cls: 'badge-success' },
  AUTHED: { label: 'Авторизованные', cls: 'badge-info' },
  MANAGER_ONLY: { label: 'Только менеджеры', cls: 'badge-warning' },
}

// --- Форма загрузки ---
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const dragging = ref(false)
const fileError = ref('')

const uploadType = ref<FileAssetType>('BRAND_PDF')
const visibility = ref<FileVisibility>('AUTHED')
const brandId = ref('')
const brands = ref<BrandRef[]>([])

const submitting = ref(false)
const submitError = ref('')
const successMsg = ref('')
let successTimer: ReturnType<typeof setTimeout> | null = null

function pickFile() {
  fileInput.value?.click()
}

function validateFile(file: File): string | null {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!ALLOWED_EXT.includes(ext)) return 'Допускаются только файлы .pdf, .csv и .zip'
  if (file.size > MAX_SIZE) return 'Файл больше 200 МБ'
  return null
}

function applyFile(file: File) {
  const err = validateFile(file)
  if (err) {
    fileError.value = err
    selectedFile.value = null
    return
  }
  fileError.value = ''
  selectedFile.value = file
}

function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) applyFile(f)
}

function onDrop(e: DragEvent) {
  dragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) applyFile(f)
}

function clearFile() {
  selectedFile.value = null
  fileError.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function resetForm() {
  clearFile()
  uploadType.value = 'BRAND_PDF'
  visibility.value = 'AUTHED'
  brandId.value = ''
}

async function onSubmit() {
  submitError.value = ''
  successMsg.value = ''
  if (!selectedFile.value) {
    submitError.value = 'Выберите файл'
    return
  }

  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('type', uploadType.value)
  fd.append('visibility', visibility.value)
  if (brandId.value) fd.append('brand_id', brandId.value)

  submitting.value = true
  try {
    // Контракт §16 п.18: 201 + {"data": FileAsset}.
    const res = await request<FileAsset & { data?: FileAsset }>('/api/v1/manager/files', {
      method: 'POST',
      body: fd,
    })
    const created = res.data ?? res
    successMsg.value = `Файл загружен: ${created.filename}`
    resetForm()
    page.value = 1
    await load()
    if (successTimer) clearTimeout(successTimer)
    successTimer = setTimeout(() => (successMsg.value = ''), 5000)
  } catch (e) {
    submitError.value = getErrorMessage(e, 'Не удалось загрузить файл')
  } finally {
    submitting.value = false
  }
}

// Бренды для привязки — тот же источник, что у каталога (GET /catalog/filters).
async function loadBrands() {
  try {
    const f = await request<FiltersOut>('/api/v1/catalog/filters')
    brands.value = f.brands
  } catch {
    // привязка к бренду опциональна — оставляем пустым
  }
}

// --- Список файлов ---
const files = ref<FileAsset[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const error = ref('')

const typeFilter = ref<'' | FileAssetType>('')
const visibilityFilter = ref<'' | FileVisibility>('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<FileAssetPage>('/api/v1/manager/files', {
      query: {
        type: typeFilter.value || undefined,
        visibility: visibilityFilter.value || undefined,
        page: page.value,
        per_page: PER_PAGE,
      },
    })
    files.value = res.data
    total.value = res.meta.total
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить список файлов')
  } finally {
    loading.value = false
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

// Окно пагинации (1 ... 4 5 6 ... 20)
function paginationWindow(total: number, current: number, window = 2): (number | '...')[] {
  const pages: (number | '...')[] = []
  const start = Math.max(2, current - window)
  const end = Math.min(total - 1, current + window)
  pages.push(1)
  if (start > 2) pages.push('...')
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < total - 1) pages.push('...')
  if (total > 1) pages.push(total)
  return pages
}

// --- Скачивание: получить presigned URL → открыть в новой вкладке ---
const downloadingId = ref<string | null>(null)
const downloadError = ref('')

async function download(f: FileAsset) {
  if (downloadingId.value) return
  downloadingId.value = f.id
  downloadError.value = ''
  try {
    // Менеджеру доступны все записи (§16 п.18) — тот же эндпоинт скачивания.
    const res = await request<FileDownloadOut & { data?: FileDownloadOut }>(
      `/api/v1/files/${f.id}/download`,
    )
    const link = res.data ?? res
    window.open(link.url, '_blank', 'noopener,noreferrer')
  } catch (e) {
    downloadError.value = getErrorMessage(e, 'Не удалось получить ссылку на файл')
  } finally {
    downloadingId.value = null
  }
}

// --- Удаление ---
const deletingId = ref<string | null>(null)

async function remove(f: FileAsset) {
  if (!window.confirm(`Удалить файл «${f.filename}»? Действие необратимо.`)) return
  deletingId.value = f.id
  error.value = ''
  try {
    await request<unknown>(`/api/v1/manager/files/${f.id}`, { method: 'DELETE' })
    // если удалили последний элемент не первой страницы — откатываемся назад
    if (files.value.length === 1 && page.value > 1) page.value--
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось удалить файл')
  } finally {
    deletingId.value = null
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

onUnmounted(() => {
  if (successTimer) clearTimeout(successTimer)
})
</script>

<template>
  <div>
    <PageHeading
      eyebrow="Сервис менеджера"
      title="Файлы"
      description="Загрузка PDF-каталогов брендов, спец-выгрузок CSV и прочих файлов для клиентов."
    />

    <!-- Форма загрузки -->
    <div class="mb-5 border border-border bg-surface p-5">
      <h2 class="font-semibold mb-4">Загрузка файла</h2>

      <!-- Dropzone -->
      <div
        class="border border-border border-2 border-dashed p-8 text-center cursor-pointer transition-colors mb-2"
        :class="dragging ? 'border-primary bg-primary-soft' : 'border-border hover:border-primary/60'"
        @click="pickFile"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,.csv,.zip"
          class="hidden"
          @change="onFileChange"
        >
        <template v-if="!selectedFile">
          <Icon name="heroicons:arrow-up-tray" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
          <p class="text-sm text-ink-muted">
            Перетащите файл сюда или нажмите для выбора
          </p>
          <p class="text-xs text-ink-faint mt-1">.pdf, .csv или .zip, до 200 МБ</p>
        </template>
        <template v-else>
          <Icon name="heroicons:document-text" class="w-10 h-10 mx-auto mb-2 text-primary" />
          <p class="text-sm font-medium text-ink break-all">{{ selectedFile.name }}</p>
          <p class="text-xs text-ink-faint mt-1">{{ formatSize(selectedFile.size) }}</p>
        </template>
      </div>

      <div v-if="fileError" class="badge-danger w-full justify-center py-2 mt-3">{{ fileError }}</div>

      <div v-if="selectedFile" class="flex justify-end mt-2">
        <button class="btn-ghost min-h-11 text-sm" @click="clearFile">
          <Icon name="heroicons:x-mark" class="w-4 h-4" /> Убрать файл
        </button>
      </div>

      <!-- Параметры файла -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
        <div>
          <label class="label" for="upload-type">Тип</label>
          <select id="upload-type" v-model="uploadType" class="input py-2.5">
            <option v-for="t in UPLOAD_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>
        <div>
          <label class="label" for="upload-visibility">Видимость</label>
          <select id="upload-visibility" v-model="visibility" class="input py-2.5">
            <option value="AUTHED">Все авторизованные</option>
            <option value="PUBLIC">Открытый</option>
            <option value="MANAGER_ONLY">Только менеджеры</option>
          </select>
        </div>
        <div>
          <label class="label" for="upload-brand">Бренд</label>
          <select id="upload-brand" v-model="brandId" class="input py-2.5">
            <option value="">Без бренда</option>
            <option v-for="b in brands" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select>
          <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
        </div>
      </div>

      <div v-if="submitError" class="badge-danger w-full justify-center py-2 mt-5">{{ submitError }}</div>
      <div v-if="successMsg" class="badge-success w-full justify-center py-2 mt-5">
        <Icon name="heroicons:check-circle" class="w-4 h-4" /> {{ successMsg }}
      </div>

      <button
        class="btn-primary w-full sm:w-auto px-6 py-3 mt-5"
        :disabled="submitting || !selectedFile"
        @click="onSubmit"
      >
        <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"/>
        {{ submitting ? 'Загрузка…' : 'Загрузить' }}
      </button>
    </div>

    <!-- Список файлов -->
    <h2 class="font-semibold mb-4">Загруженные файлы</h2>

    <!-- Фильтры -->
    <div class="flex flex-col sm:flex-row gap-4 mb-6">
      <div class="sm:w-64">
        <label class="label" for="type">Тип</label>
        <select id="type" v-model="typeFilter" class="input py-2.5" @change="applyFilters">
          <option value="">Все типы</option>
          <option v-for="(meta, t) in TYPE_META" :key="t" :value="t">{{ meta.label }}</option>
        </select>
      </div>
      <div class="sm:w-64">
        <label class="label" for="visibility">Видимость</label>
        <select id="visibility" v-model="visibilityFilter" class="input py-2.5" @change="applyFilters">
          <option value="">Любая</option>
          <option value="PUBLIC">Открытый</option>
          <option value="AUTHED">Авторизованные</option>
          <option value="MANAGER_ONLY">Только менеджеры</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost min-h-11 text-sm" @click="load()">Повторить</button>
    </div>
    <div v-if="downloadError" class="badge-danger w-full justify-center py-2 mb-4">
      {{ downloadError }}
    </div>

    <!-- Скелетоны -->
    <div v-if="loading" class="border border-border bg-surface p-4">
      <div v-for="i in 4" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <!-- Пусто -->
    <div v-else-if="!files.length" class="border border-border bg-surface p-6 text-ink-muted">
      <Icon name="heroicons:folder" class="size-8 mb-3 text-ink-faint" />
      <p>Файлов пока нет</p>
    </div>

    <!-- Таблица -->
    <div v-else class="border border-border bg-surface">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-surface-2 border-b border-border">
              <th class="px-4 py-3 font-medium">Имя</th>
              <th class="px-4 py-3 font-medium">Тип</th>
              <th class="px-4 py-3 font-medium">Бренд</th>
              <th class="px-4 py-3 font-medium">Видимость</th>
              <th class="px-4 py-3 font-medium">Размер</th>
              <th class="px-4 py-3 font-medium">Дата</th>
              <th class="px-4 py-3 font-medium text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in files"
              :key="f.id"
              class="border-t border-border hover:bg-canvas/60"
            >
              <td class="px-4 py-3 max-w-[220px] truncate" :title="f.filename">{{ f.filename }}</td>
              <td class="px-4 py-3">
                <span class="badge-info">{{ TYPE_META[f.type]?.label || f.type }}</span>
              </td>
              <td class="px-4 py-3 text-ink-muted">{{ f.brand_name || '—' }}</td>
              <td class="px-4 py-3">
                <span :class="VISIBILITY_META[f.visibility]?.cls || 'badge-info'">
                  {{ VISIBILITY_META[f.visibility]?.label || f.visibility }}
                </span>
              </td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatSize(f.size_bytes) }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(f.created_at) }}</td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <button
                  class="btn-ghost min-h-11 text-sm"
                  :disabled="downloadingId === f.id"
                  @click="download(f)"
                >
                  <span
                    v-if="downloadingId === f.id"
                    class="w-4 h-4 border-2 border-current/40 border-t-current rounded-sm animate-spin"
                  />
                  <Icon v-else name="heroicons:arrow-down-tray" class="w-4 h-4" />
                  Скачать
                </button>
                <button
                  class="btn-ghost min-h-11 text-sm text-danger"
                  :disabled="deletingId === f.id"
                  @click="remove(f)"
                >
                  <span
                    v-if="deletingId === f.id"
                    class="w-4 h-4 border-2 border-current/40 border-t-current rounded-sm animate-spin"
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
      <button class="btn-ghost size-11" :disabled="page <= 1" @click="goPage(page - 1)">
        <Icon name="heroicons:chevron-left" class="w-5 h-5" />
      </button>
      <template v-for="(pgn, idx) in paginationWindow(totalPages, page)" :key="idx">
        <span v-if="pgn === '...'" class="px-2 text-ink-faint">…</span>
        <button
          v-else
          class="btn-outline size-11 font-medium text-sm"
          :class="pgn === page ? 'border-action bg-action text-white' : 'text-ink-muted hover:bg-surface-2'"
          @click="goPage(pgn as number)"
        >{{ pgn }}</button>
      </template>
      <button class="btn-ghost size-11" :disabled="page >= totalPages" @click="goPage(page + 1)">
        <Icon name="heroicons:chevron-right" class="w-5 h-5" />
      </button>
    </nav>
  </div>
</template>
