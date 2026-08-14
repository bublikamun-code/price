<script setup lang="ts">
// Импорт прайс-листа (менеджер). См. SITEMAP.md §7, ARCHITECTURE_PLAN.md §6.
// Реальные данные: POST /manager/prices/import, GET /manager/prices/versions[/{id}[/errors]].
// Вкладка «Изменения цен» и rollback отсутствуют — эндпоинтов пока нет в бэкенде.
import type {
  ImportMode,
  ImportUploadOut,
  PriceListVersionRead,
  PriceListVersionPage,
} from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER'] })
useHead({ title: 'Импорт прайс-листа' })

const { request } = useApi()

const PER_PAGE = 10
const MAX_SIZE = 100 * 1024 * 1024 // settings.import_max_file_mb = 100
const ALLOWED_EXT = ['.csv', '.txt']
const CURRENCIES = ['BYN', 'USD', 'EUR', 'RUB']

const MODES: { value: ImportMode; label: string; hint: string }[] = [
  { value: 'UPSERT', label: 'Upsert', hint: 'Обновить и добавить новые позиции' },
  { value: 'REPLACE', label: 'Replace', hint: 'Полная замена каталога' },
  { value: 'ARCHIVE_MISSING', label: 'Archive-missing', hint: 'Архивировать отсутствующие в файле' },
]

const STATUS_META: Record<string, { label: string; cls: string }> = {
  QUEUED: { label: 'В очереди', cls: 'badge-info' },
  PROCESSING: { label: 'Обработка', cls: 'badge-info' },
  DONE: { label: 'Готово', cls: 'badge-success' },
  FAILED: { label: 'Ошибка', cls: 'badge-danger' },
}

// --- Форма загрузки ---
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const dragging = ref(false)
const fileError = ref('')

const mode = ref<ImportMode>('UPSERT')
const baseCurrency = ref('BYN')
const rateToByn = ref<number>(1)
const submitting = ref(false)
const submitError = ref('')
const successMsg = ref('')
let successTimer: ReturnType<typeof setTimeout> | null = null

const rateDisabled = computed(() => baseCurrency.value === 'BYN')

function pickFile() {
  fileInput.value?.click()
}

function validateFile(file: File): string | null {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!ALLOWED_EXT.includes(ext)) return 'Допускаются только файлы .csv и .txt'
  if (file.size > MAX_SIZE) return 'Файл больше 100 МБ'
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function onCurrencyChange() {
  if (baseCurrency.value === 'BYN') rateToByn.value = 1
}

async function onSubmit() {
  submitError.value = ''
  successMsg.value = ''
  if (!selectedFile.value) {
    submitError.value = 'Выберите файл прайс-листа'
    return
  }
  if (!rateDisabled.value && (!rateToByn.value || rateToByn.value <= 0)) {
    submitError.value = 'Курс должен быть больше 0'
    return
  }

  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('mode', mode.value)
  fd.append('base_currency', baseCurrency.value)
  fd.append('rate_to_byn', String(rateDisabled.value ? 1 : rateToByn.value))

  submitting.value = true
  try {
    const res = await request<ImportUploadOut>('/api/v1/manager/prices/import', {
      method: 'POST',
      body: fd,
    })
    successMsg.value = `Импорт запущен: ${res.filename}`
    clearFile()
    page.value = 1
    await loadHistory()
    if (successTimer) clearTimeout(successTimer)
    successTimer = setTimeout(() => (successMsg.value = ''), 4000)
  } catch (e) {
    submitError.value = getErrorMessage(e, 'Не удалось запустить импорт')
  } finally {
    submitting.value = false
  }
}

// --- История импортов ---
const versions = ref<PriceListVersionRead[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function loadHistory(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  try {
    const res = await request<PriceListVersionPage>('/api/v1/manager/prices/versions', {
      query: { page: page.value, per_page: PER_PAGE },
    })
    versions.value = res.data
    total.value = res.meta.total
  } catch (e) {
    if (!silent) error.value = getErrorMessage(e, 'Не удалось загрузить историю импортов')
  } finally {
    if (!silent) loading.value = false
  }
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  loadHistory()
}

function progress(v: PriceListVersionRead): number {
  if (!v.rows_total) return 0
  return Math.min(100, Math.round(((v.rows_ok + v.rows_error) / v.rows_total) * 100))
}

function formatDate(s: string | null): string {
  if (!s) return '—'
  return new Date(s).toLocaleString('ru-RU')
}

// --- Live-поллинг активных импортов ---
let pollTimer: ReturnType<typeof setInterval> | null = null

function maybePoll() {
  const active = versions.value.some(
    (v) => v.status === 'QUEUED' || v.status === 'PROCESSING',
  )
  if (active) loadHistory(true)
}

// --- Модалка деталей версии ---
const showModal = ref(false)
const selectedVersionId = ref<string | null>(null)
const detail = ref<PriceListVersionRead | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const errorsUrlLoading = ref(false)

async function openDetails(id: string) {
  selectedVersionId.value = id
  showModal.value = true
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    detail.value = await request<PriceListVersionRead>(
      `/api/v1/manager/prices/versions/${id}`,
    )
  } catch (e) {
    detailError.value = getErrorMessage(e, 'Не удалось загрузить версию')
  } finally {
    detailLoading.value = false
  }
}

function closeModal() {
  showModal.value = false
  selectedVersionId.value = null
  detail.value = null
  detailError.value = ''
}

async function downloadErrors() {
  if (!selectedVersionId.value || !detail.value?.error_log_key) return
  errorsUrlLoading.value = true
  detailError.value = ''
  try {
    const res = await request<{ url: string }>(
      `/api/v1/manager/prices/versions/${selectedVersionId.value}/errors`,
    )
    window.open(res.url, '_blank')
  } catch (e) {
    detailError.value = getErrorMessage(e, 'Не удалось получить ссылку на лог ошибок')
  } finally {
    errorsUrlLoading.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && showModal.value) closeModal()
}

onMounted(async () => {
  await loadHistory()
  pollTimer = setInterval(maybePoll, 5000)
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (successTimer) clearTimeout(successTimer)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Импорт прайс-листа</h1>
      <p class="text-sm text-ink-muted mt-1">
        Загрузите CSV-файл. Импорт выполняется в фоне — статус виден в истории ниже.
      </p>
    </div>

    <!-- Форма загрузки -->
    <div class="card p-6 mb-8">
      <h2 class="font-semibold mb-4">Новый импорт</h2>

      <!-- Dropzone -->
      <div
        class="rounded-card border-2 border-dashed p-8 text-center cursor-pointer transition-colors mb-2"
        :class="dragging ? 'border-primary bg-primary-soft' : 'border-border hover:border-primary/60'"
        @click="pickFile"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".csv,.txt"
          class="hidden"
          @change="onFileChange"
        >
        <template v-if="!selectedFile">
          <Icon name="heroicons:arrow-up-tray" class="w-10 h-10 mx-auto mb-2 text-ink-faint" />
          <p class="text-sm text-ink-muted">
            Перетащите CSV сюда или нажмите для выбора
          </p>
          <p class="text-xs text-ink-faint mt-1">.csv или .txt, до 100 МБ</p>
        </template>
        <template v-else>
          <Icon name="heroicons:document-text" class="w-10 h-10 mx-auto mb-2 text-primary" />
          <p class="text-sm font-medium text-ink break-all">{{ selectedFile.name }}</p>
          <p class="text-xs text-ink-faint mt-1">{{ formatSize(selectedFile.size) }}</p>
        </template>
      </div>

      <div v-if="fileError" class="badge-danger w-full justify-center py-2 mt-3">{{ fileError }}</div>

      <div v-if="selectedFile" class="flex justify-end mt-2">
        <button class="btn-ghost text-sm" @click="clearFile">
          <Icon name="heroicons:x-mark" class="w-4 h-4" /> Убрать файл
        </button>
      </div>

      <!-- Режим импорта -->
      <div class="mt-6">
        <label class="label">Режим импорта</label>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <button
            v-for="m in MODES"
            :key="m.value"
            type="button"
            class="text-left p-4 rounded-card border transition-all"
            :class="mode === m.value
              ? 'border-primary bg-primary-soft'
              : 'border-border bg-surface hover:border-primary/60'"
            @click="mode = m.value"
          >
            <span class="block font-semibold text-sm" :class="mode === m.value ? 'text-primary' : 'text-ink'">
              {{ m.label }}
            </span>
            <span class="block text-xs text-ink-muted mt-1">{{ m.hint }}</span>
          </button>
        </div>
      </div>

      <!-- Валюта + курс -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6">
        <div>
          <label class="label" for="currency">Валюта прайса</label>
          <select id="currency" v-model="baseCurrency" class="input py-2.5" @change="onCurrencyChange">
            <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div>
          <label class="label" for="rate">Курс к BYN</label>
          <input
            id="rate"
            v-model.number="rateToByn"
            type="number"
            min="0"
            step="0.0001"
            class="input py-2.5"
            :disabled="rateDisabled"
          >
          <p class="text-xs text-ink-faint mt-1.5">
            Форсируется в 1.0 при выборе BYN
          </p>
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
        <span v-if="submitting" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"/>
        {{ submitting ? 'Запуск…' : 'Импортировать' }}
      </button>
    </div>

    <!-- История импортов -->
    <h2 class="font-semibold mb-4">История импортов</h2>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="loadHistory()">Повторить</button>
    </div>

    <div v-if="loading" class="card p-5">
      <div v-for="i in 4" :key="i" class="skeleton h-12 w-full mb-3 last:mb-0"/>
    </div>

    <div v-else-if="!versions.length" class="card p-10 text-center text-ink-muted">
      <Icon name="heroicons:clock" class="w-10 h-10 mx-auto mb-3 text-ink-faint" />
      <p>Импортов пока не было</p>
    </div>

    <div v-else class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-ink-muted text-left bg-canvas">
              <th class="px-4 py-3 font-medium">Файл</th>
              <th class="px-4 py-3 font-medium">Дата</th>
              <th class="px-4 py-3 font-medium">Режим</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium min-w-[140px]">Прогресс</th>
              <th class="px-4 py-3 font-medium">Ошибки</th>
              <th class="px-4 py-3 font-medium text-right">Действие</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="v in versions"
              :key="v.id"
              class="border-t border-border hover:bg-canvas/60"
            >
              <td class="px-4 py-3 max-w-[200px] truncate" :title="v.filename">{{ v.filename }}</td>
              <td class="px-4 py-3 text-ink-muted whitespace-nowrap">{{ formatDate(v.created_at) }}</td>
              <td class="px-4 py-3 text-ink-muted">{{ v.import_mode }}</td>
              <td class="px-4 py-3">
                <span :class="STATUS_META[v.status]?.cls || 'badge-info'">
                  {{ STATUS_META[v.status]?.label || v.status }}
                </span>
              </td>
              <td class="px-4 py-3">
                <template v-if="!v.rows_total && (v.status === 'QUEUED' || v.status === 'PROCESSING')">
                  <span class="text-xs text-ink-faint">Ожидание…</span>
                </template>
                <template v-else>
                  <div class="flex items-center gap-2">
                    <div class="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden min-w-[80px]">
                      <div class="h-full bg-primary transition-all" :style="{ width: progress(v) + '%' }"/>
                    </div>
                    <span class="text-xs text-ink-muted w-9 text-right">{{ progress(v) }}%</span>
                  </div>
                </template>
              </td>
              <td class="px-4 py-3">
                <span :class="v.rows_error > 0 ? 'text-danger font-semibold' : 'text-ink-muted'">
                  {{ v.rows_error }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button class="btn-ghost text-sm py-1.5" @click="openDetails(v.id)">
                  <Icon name="heroicons:eye" class="w-4 h-4" /> Детали
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

    <!-- Модалка деталей версии -->
    <div
      v-if="showModal"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      @click.self="closeModal"
    >
      <div class="card max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div class="flex items-start justify-between gap-4 mb-5">
          <div class="min-w-0">
            <h3 class="font-semibold truncate">Детали импорта</h3>
            <p v-if="detail" class="text-sm text-ink-muted truncate mt-0.5">{{ detail.filename }}</p>
          </div>
          <button class="btn-ghost p-2 -mr-2 shrink-0" @click="closeModal">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div v-if="detailLoading" class="space-y-3">
          <div class="skeleton h-8 w-full"/>
          <div class="skeleton h-8 w-full"/>
          <div class="skeleton h-8 w-full"/>
        </div>

        <template v-else-if="detail">
          <div class="flex items-center gap-3 mb-5">
            <span :class="STATUS_META[detail.status]?.cls || 'badge-info'">
              {{ STATUS_META[detail.status]?.label || detail.status }}
            </span>
            <span class="text-sm text-ink-muted">{{ detail.import_mode }}</span>
          </div>

          <!-- Прогресс -->
          <div v-if="detail.rows_total" class="mb-5">
            <div class="flex items-center gap-2 mb-1.5">
              <div class="flex-1 h-2.5 bg-surface-2 rounded-full overflow-hidden">
                <div class="h-full bg-primary transition-all" :style="{ width: progress(detail) + '%' }"/>
              </div>
              <span class="text-sm font-medium w-10 text-right">{{ progress(detail) }}%</span>
            </div>
          </div>

          <!-- Агрегаты -->
          <div class="grid grid-cols-3 gap-3 mb-5">
            <div class="card p-4 text-center">
              <p class="text-xs text-ink-muted mb-1">Всего строк</p>
              <p class="text-xl font-bold">{{ detail.rows_total }}</p>
            </div>
            <div class="card p-4 text-center">
              <p class="text-xs text-ink-muted mb-1">Успешно</p>
              <p class="text-xl font-bold text-success">{{ detail.rows_ok }}</p>
            </div>
            <div class="card p-4 text-center">
              <p class="text-xs text-ink-muted mb-1">Ошибок</p>
              <p class="text-xl font-bold" :class="detail.rows_error > 0 ? 'text-danger' : ''">
                {{ detail.rows_error }}
              </p>
            </div>
          </div>

          <!-- Курс -->
          <div class="card p-4 mb-5 text-sm">
            <div class="flex justify-between py-1">
              <span class="text-ink-muted">Валюта прайса</span>
              <span class="font-medium">{{ detail.base_currency }}</span>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-ink-muted">Курс к BYN</span>
              <span class="font-medium">{{ detail.rate_to_byn }}</span>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-ink-muted">Источник курса</span>
              <span class="font-medium">{{ detail.rate_source || '—' }}</span>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-ink-muted">Начат</span>
              <span class="font-medium">{{ formatDate(detail.started_at) }}</span>
            </div>
            <div class="flex justify-between py-1">
              <span class="text-ink-muted">Завершён</span>
              <span class="font-medium">{{ formatDate(detail.finished_at) }}</span>
            </div>
          </div>

          <div v-if="detailError" class="badge-danger w-full justify-center py-2 mb-4">{{ detailError }}</div>

          <div class="flex justify-end gap-2">
            <button
              class="btn-secondary"
              :disabled="!detail.error_log_key || detail.rows_error === 0 || errorsUrlLoading"
              @click="downloadErrors"
            >
              <span v-if="errorsUrlLoading" class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"/>
              <Icon v-else name="heroicons:arrow-down-tray" class="w-4 h-4" />
              Скачать лог ошибок
            </button>
            <button class="btn-ghost" @click="closeModal">Закрыть</button>
          </div>
        </template>

        <div v-else-if="detailError" class="text-center py-8">
          <p class="text-danger text-sm">{{ detailError }}</p>
          <button class="btn-ghost mt-3" @click="selectedVersionId && openDetails(selectedVersionId)">
            Повторить
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
