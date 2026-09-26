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

const typeFilter = ref('')
const brandFilter = ref('')
const brands = ref<BrandRef[]>([])

const typeOptions = [
  { value: '', label: 'Все файлы' },
  { value: 'BRAND_PDF', label: 'PDF-каталог бренда' },
  { value: 'CUSTOM_CSV', label: 'Спец-выгрузка CSV' },
  { value: 'OTHER', label: 'Прочее' },
]
const brandOptions = computed(() => [
  { value: '', label: 'Все бренды' },
  ...brands.value.map((b) => ({ value: b.id, label: b.name })),
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PER_PAGE)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request<FileAssetPage>('/api/v1/files', {
      query: {
        type: (typeFilter.value || undefined) as FileAssetType | undefined,
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
    window.open(link.url, '_blank', 'noopener,noreferrer')
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
    <PageHeading
      eyebrow="Рабочий кабинет"
      title="Файлы"
      description="PDF-каталоги брендов и специальные выгрузки для скачивания."
    />

    <div class="mb-6 flex flex-col gap-4 sm:flex-row">
      <UiField for="files-type" label="Тип" class="sm:w-64">
        <UiSelect v-model="typeFilter" :options="typeOptions" @update:model-value="applyFilters" />
      </UiField>
      <UiField v-if="brands.length" for="files-brand" label="Бренд" class="sm:w-64">
        <UiSelect v-model="brandFilter" :options="brandOptions" @update:model-value="applyFilters" />
      </UiField>
    </div>

    <UiErrorState
      v-if="error"
      class="mb-4"
      title="Не удалось загрузить файлы"
      :description="error"
      data-testid="files-error"
      @retry="load"
    />
    <UiErrorState
      v-if="downloadError"
      class="mb-4"
      title="Не удалось получить ссылку на файл"
      :description="downloadError"
      data-testid="files-download-error"
    />

    <UiLoadingState v-if="loading" class="min-h-64" label="Загрузка файлов" />

    <UiEmptyState
      v-else-if="!files.length"
      icon="heroicons:folder-open"
      title="Файлов пока нет"
      description="PDF-каталоги брендов и выгрузки появятся здесь после загрузки менеджером."
    />

    <template v-else>
      <div class="hidden md:block">
        <UiTableFrame caption="Файлы" overflow-label="Файлы">
          <template #header>
            <tr class="border-b border-border bg-surface-2 text-xs font-semibold text-ink-muted">
              <th scope="col" class="w-64 px-3 py-2">Имя</th>
              <th scope="col" class="w-44 px-3 py-2">Тип</th>
              <th scope="col" class="px-3 py-2">Бренд</th>
              <th scope="col" class="w-28 px-3 py-2">Размер</th>
              <th scope="col" class="w-44 px-3 py-2">Дата</th>
              <th scope="col" class="w-32 px-3 py-2 text-right">Действие</th>
            </tr>
          </template>
          <tr
            v-for="f in files"
            :key="f.id"
            class="border-b border-border hover:bg-surface-2"
            :data-testid="`files-row-${f.id}`"
          >
            <td class="max-w-0 truncate px-3 py-2" :title="f.filename">{{ f.filename }}</td>
            <td class="px-3 py-2">
              <UiStatusBadge tone="neutral" :label="TYPE_META[f.type]?.label || f.type" />
            </td>
            <td class="px-3 py-2 text-ink-muted">{{ f.brand_name || '—' }}</td>
            <td class="numeric whitespace-nowrap px-3 py-2 text-ink-muted">{{ formatSize(f.size_bytes) }}</td>
            <td class="whitespace-nowrap px-3 py-2 text-ink-muted">{{ formatDate(f.created_at) }}</td>
            <td class="px-3 py-2 text-right">
              <UiButton
                variant="outline"
                size="compact"
                :loading="downloadingId === f.id"
                :aria-label="`Скачать ${f.filename}`"
                :data-testid="`files-download-${f.id}`"
                @click="download(f)"
              >
                <Icon name="heroicons:arrow-down-tray" class="size-4" aria-hidden="true" />
                Скачать
              </UiButton>
            </td>
          </tr>
        </UiTableFrame>
      </div>

      <div class="md:hidden" data-testid="files-records">
        <article
          v-for="f in files"
          :key="f.id"
          class="flex items-start gap-3 border-b border-border py-4"
        >
          <div class="min-w-0 flex-1">
            <p class="line-clamp-2 text-sm font-semibold leading-5 text-ink">{{ f.filename }}</p>
            <p class="mt-1 text-xs text-ink-muted">
              {{ TYPE_META[f.type]?.label || f.type }}<span v-if="f.brand_name"> · {{ f.brand_name }}</span>
            </p>
            <p class="numeric mt-1 text-xs text-ink-muted">
              {{ formatSize(f.size_bytes) }} · {{ formatDate(f.created_at) }}
            </p>
          </div>
          <UiButton
            variant="outline"
            size="touch"
            class="shrink-0 px-3"
            :loading="downloadingId === f.id"
            :aria-label="`Скачать ${f.filename}`"
            :data-testid="`files-download-m-${f.id}`"
            @click="download(f)"
          >
            <Icon name="heroicons:arrow-down-tray" class="size-4" aria-hidden="true" />
            Скачать
          </UiButton>
        </article>
      </div>

      <UiPagination
        v-if="totalPages > 1"
        class="mt-6"
        :page="page"
        :page-count="totalPages"
        :total="total"
        label="Страницы файлов"
        @update:page="goPage"
      />
    </template>
  </div>
</template>
