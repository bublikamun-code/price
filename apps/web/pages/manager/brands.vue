<script setup lang="ts">
// Бренды и серии (менеджер, Этап 8 п.20-3): CRUD брендов, фото серий.
// Бренды — GET/POST/PATCH/DELETE /api/v1/manager/brands; серии и их фото —
// GET /api/v1/catalog/filters + POST /api/v1/manager/series/{id}/photo.
import type { FiltersOut, ManagerBrand, SeriesPhotoOut, SeriesRef } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Бренды и серии — Менеджер' })

const { request } = useApi()
/* закрытие модалки по клику на подложку — только если нажатие началось на ней (иначе срабатывает при выделении текста с уводом мыши) */
const overlayDown = ref(false)
const { thumbOf } = useProductPhoto()

const SERIES_COLLAPSE_AT = 6 // больше — сворачиваем с «Показать все»

const loading = ref(true)
const error = ref('')
const brands = ref<ManagerBrand[]>([])
const filters = ref<FiltersOut | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    // Параллельно: бренды со счётчиками + серии с фото из фильтров каталога.
    const [b, f] = await Promise.all([
      request<ManagerBrand[]>('/api/v1/manager/brands'),
      request<FiltersOut>('/api/v1/catalog/filters'),
    ])
    brands.value = b
    filters.value = f
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить бренды')
  } finally {
    loading.value = false
  }
}

// Серии по бренду (у SeriesRef из filters есть brand_id и photo_key).
function seriesOf(brandId: string): SeriesRef[] {
  return (filters.value?.series ?? []).filter((s) => s.brand_id === brandId)
}

const expanded = ref<string[]>([])

function isExpanded(brandId: string): boolean {
  return expanded.value.includes(brandId)
}

function toggleExpand(brandId: string) {
  expanded.value = isExpanded(brandId)
    ? expanded.value.filter((x) => x !== brandId)
    : [...expanded.value, brandId]
}

function visibleSeries(brandId: string): SeriesRef[] {
  const all = seriesOf(brandId)
  return all.length > SERIES_COLLAPSE_AT && !isExpanded(brandId) ? all.slice(0, SERIES_COLLAPSE_AT) : all
}

// --- Создание бренда ---
const showCreate = ref(false)
const createName = ref('')
const creating = ref(false)
const createError = ref('')

function openCreate() {
  createName.value = ''
  createError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  const name = createName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  createError.value = ''
  try {
    const res = await request<ManagerBrand>('/api/v1/manager/brands', { method: 'POST', body: { name } })
    brands.value.unshift(res)
    showCreate.value = false
  } catch (e) {
    createError.value = getErrorMessage(e, 'Не удалось создать бренд')
  } finally {
    creating.value = false
  }
}

// --- Переименование бренда (slug стабилен) ---
const renaming = ref<ManagerBrand | null>(null)
const renameName = ref('')
const renamingBusy = ref(false)
const renameError = ref('')

function openRename(b: ManagerBrand) {
  renaming.value = b
  renameName.value = b.name
  renameError.value = ''
}

async function submitRename() {
  if (!renaming.value) return
  const name = renameName.value.trim()
  if (!name || renamingBusy.value) return
  renamingBusy.value = true
  renameError.value = ''
  try {
    const res = await request<ManagerBrand>(`/api/v1/manager/brands/${renaming.value.id}`, {
      method: 'PATCH',
      body: { name },
    })
    brands.value = brands.value.map((b) => (b.id === res.id ? res : b))
    renaming.value = null
  } catch (e) {
    renameError.value = getErrorMessage(e, 'Не удалось переименовать бренд')
  } finally {
    renamingBusy.value = false
  }
}

// --- Удаление бренда (409 — есть серии/товары) ---
const confirmingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const deleteError = ref<{ id: string; msg: string } | null>(null)

function confirmDelete(b: ManagerBrand) {
  deleteError.value = null
  confirmingId.value = confirmingId.value === b.id ? null : b.id
}

async function doDelete(b: ManagerBrand) {
  if (deletingId.value) return
  deletingId.value = b.id
  deleteError.value = null
  try {
    await request(`/api/v1/manager/brands/${b.id}`, { method: 'DELETE' })
    brands.value = brands.value.filter((x) => x.id !== b.id)
    confirmingId.value = null
  } catch (e) {
    deleteError.value = { id: b.id, msg: getErrorMessage(e, 'Не удалось удалить бренд') }
  } finally {
    deletingId.value = null
  }
}

// --- Фото серии (multipart file → photo_key; JPG/PNG/WebP до 20 МБ) ---
const MAX_PHOTO_BYTES = 20 * 1024 * 1024
const uploadingId = ref<string | null>(null)
const uploadError = ref<{ id: string; msg: string } | null>(null)

async function onPhotoPick(s: SeriesRef, ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // чтобы повторно можно было выбрать тот же файл
  if (!file || uploadingId.value) return
  uploadError.value = null

  // Клиентская валидация (сервер тоже проверяет: 415/413).
  if (!/\.(jpe?g|png|webp)$/i.test(file.name)) {
    uploadError.value = { id: s.id, msg: 'Допустимы только JPG, PNG или WebP' }
    return
  }
  if (file.size > MAX_PHOTO_BYTES) {
    uploadError.value = { id: s.id, msg: 'Файл больше 20 МБ' }
    return
  }

  uploadingId.value = s.id
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await request<SeriesPhotoOut>(`/api/v1/manager/series/${s.id}/photo`, {
      method: 'POST',
      body: fd,
    })
    s.photo_key = res.photo_key // обновляем фото на месте
  } catch (e) {
    uploadError.value = { id: s.id, msg: getErrorMessage(e, 'Не удалось загрузить фото') }
  } finally {
    uploadingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold">Бренды и серии</h1>
        <p class="text-sm text-ink-muted mt-1">
          <template v-if="!loading">{{ brands.length }} брендов</template>
          <template v-else>Загрузка…</template>
        </p>
      </div>
      <button class="btn-primary shrink-0" @click="openCreate">
        <Icon name="heroicons:plus" class="w-4 h-4" /> Создать бренд
      </button>
    </div>

    <div v-if="error" class="flex items-center gap-3 mb-4">
      <div class="badge-danger">{{ error }}</div>
      <button class="btn-ghost text-sm" @click="load">Повторить</button>
    </div>

    <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      <div v-for="i in 6" :key="i" class="card p-5">
        <div class="skeleton h-5 w-1/2 mb-2" />
        <div class="skeleton h-3.5 w-1/3 mb-4" />
        <div class="skeleton h-10 w-full" />
      </div>
    </div>

    <div v-else-if="!brands.length" class="card p-12 text-center text-ink-muted">
      <Icon name="heroicons:tag" class="w-12 h-12 mx-auto mb-3 text-ink-faint" />
      <p>Брендов пока нет</p>
      <button class="btn-primary mt-4" @click="openCreate">
        <Icon name="heroicons:plus" class="w-4 h-4" /> Создать первый бренд
      </button>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      <div v-for="b in brands" :key="b.id" class="card p-5 flex flex-col">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="font-semibold truncate" :title="b.name">{{ b.name }}</h3>
            <p class="text-xs text-ink-faint font-mono mt-0.5 truncate">{{ b.slug }}</p>
          </div>
          <div class="flex gap-1 shrink-0">
            <button class="btn-ghost text-xs py-1.5 px-2.5" @click="openRename(b)">
              <Icon name="heroicons:pencil" class="w-3.5 h-3.5" /> Переименовать
            </button>
            <button class="btn-ghost text-xs py-1.5 px-2.5 text-danger" @click="confirmDelete(b)">
              <Icon name="heroicons:trash" class="w-3.5 h-3.5" /> Удалить
            </button>
          </div>
        </div>

        <p class="text-sm text-ink-muted mt-2">
          серий {{ b.series_count }} • товаров {{ b.products_count }}
        </p>

        <!-- Подтверждение удаления -->
        <div v-if="confirmingId === b.id" class="flex items-center gap-2 mt-3 p-3 rounded-lg bg-danger-soft">
          <span class="text-xs text-danger flex-1">Удалить бренд «{{ b.name }}»?</span>
          <button
            class="btn-outline text-xs py-1.5 px-3 text-danger border-danger"
            :disabled="deletingId === b.id"
            @click="doDelete(b)"
          >
            <span v-if="deletingId === b.id" class="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ deletingId === b.id ? 'Удаление…' : 'Удалить' }}
          </button>
          <button class="btn-ghost text-xs py-1.5 px-3" @click="confirmingId = null">Отмена</button>
        </div>
        <div v-if="deleteError?.id === b.id" class="badge-danger mt-3">{{ deleteError.msg }}</div>

        <!-- Серии с фото -->
        <div class="mt-4 pt-4 border-t border-border flex-1">
          <div v-if="!seriesOf(b.id).length" class="text-sm text-ink-faint">
            Нет серий
          </div>
          <ul v-else class="space-y-2">
            <li v-for="s in visibleSeries(b.id)" :key="s.id">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg overflow-hidden bg-canvas shrink-0 flex items-center justify-center">
                  <img
                    v-if="thumbOf(s.photo_key)"
                    :src="thumbOf(s.photo_key) || ''"
                    :alt="`Фото серии ${s.name}`"
                    class="w-full h-full object-cover"
                  >
                  <Icon v-else name="heroicons:photo" class="w-5 h-5 text-ink-faint" />
                </div>
                <span class="text-sm truncate flex-1" :title="s.name">{{ s.name }}</span>
                <label
                  class="btn-ghost text-xs py-1.5 px-2.5 cursor-pointer shrink-0"
                  :class="{ 'pointer-events-none opacity-60': uploadingId === s.id }"
                >
                  <input
                    type="file"
                    class="hidden"
                    accept=".jpg,.jpeg,.png,.webp"
                    @change="onPhotoPick(s, $event)"
                  >
                  <span v-if="uploadingId === s.id" class="w-3.5 h-3.5 border-2 border-primary/40 border-t-primary rounded-full animate-spin" />
                  <Icon v-else name="heroicons:camera" class="w-3.5 h-3.5" />
                  {{ s.photo_key ? 'Заменить' : 'Загрузить фото' }}
                </label>
              </div>
              <p v-if="uploadError?.id === s.id" class="text-xs text-danger mt-1 pl-12">{{ uploadError.msg }}</p>
            </li>
          </ul>
          <button
            v-if="seriesOf(b.id).length > SERIES_COLLAPSE_AT"
            class="btn-ghost text-xs py-1.5 px-2.5 mt-2"
            @click="toggleExpand(b.id)"
          >
            {{ isExpanded(b.id) ? 'Свернуть' : `Показать все (${seriesOf(b.id).length})` }}
          </button>
        </div>
      </div>
    </div>

    <!-- Создание бренда -->
    <div
      v-if="showCreate"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) showCreate = false; overlayDown = false"
    >
      <form class="card max-w-lg w-full p-6" @submit.prevent="submitCreate">
        <div class="flex items-start justify-between gap-4 mb-5">
          <h3 class="font-semibold">Новый бренд</h3>
          <button type="button" class="btn-ghost p-2 -mr-2 shrink-0" @click="showCreate = false">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>
        <div>
          <label class="label" for="brand-name">Название <span class="text-danger">*</span></label>
          <input
            id="brand-name"
            v-model="createName"
            type="text"
            class="input"
            placeholder="Напр. DIGITEX"
            required
            maxlength="255"
          >
          <p class="text-xs text-ink-faint mt-1.5">Slug сгенерируется автоматически из названия.</p>
        </div>
        <div v-if="createError" class="badge-danger w-full justify-center py-2 mt-5">{{ createError }}</div>
        <div class="flex justify-end gap-2 mt-6">
          <button type="button" class="btn-ghost" @click="showCreate = false">Отмена</button>
          <button type="submit" class="btn-primary" :disabled="!createName.trim() || creating">
            <span v-if="creating" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ creating ? 'Создание…' : 'Создать' }}
          </button>
        </div>
      </form>
    </div>

    <!-- Переименование бренда -->
    <div
      v-if="renaming"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      @mousedown.self="overlayDown = true" @click.self="if (overlayDown) renaming = null; overlayDown = false"
    >
      <form class="card max-w-lg w-full p-6" @submit.prevent="submitRename">
        <div class="flex items-start justify-between gap-4 mb-5">
          <div class="min-w-0">
            <h3 class="font-semibold">Переименовать бренд</h3>
            <p class="text-xs text-ink-faint font-mono mt-0.5">{{ renaming.slug }} — slug не изменится</p>
          </div>
          <button type="button" class="btn-ghost p-2 -mr-2 shrink-0" @click="renaming = null">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>
        <div>
          <label class="label" for="rename-name">Название <span class="text-danger">*</span></label>
          <input
            id="rename-name"
            v-model="renameName"
            type="text"
            class="input"
            required
            maxlength="255"
          >
        </div>
        <div v-if="renameError" class="badge-danger w-full justify-center py-2 mt-5">{{ renameError }}</div>
        <div class="flex justify-end gap-2 mt-6">
          <button type="button" class="btn-ghost" @click="renaming = null">Отмена</button>
          <button type="submit" class="btn-primary" :disabled="!renameName.trim() || renamingBusy">
            <span v-if="renamingBusy" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ renamingBusy ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
