<script setup lang="ts">
// Маркетинговые баннеры главной (менеджер). CRUD: /api/v1/manager/banners,
// загрузка изображения — POST /api/v1/manager/banners/image (multipart, поле file).
import type { BannerCreate, BannerLinkType, BannerPosition, BannerRead } from '~/types/api'

definePageMeta({ layout: 'manager', middleware: ['auth', 'role'], roles: ['MANAGER', 'ADMIN'] })
useHead({ title: 'Баннеры — Менеджер' })

const { request } = useApi()
const { urlOf } = useProductPhoto()

const POSITION_META: Record<BannerPosition, { label: string; cls: string }> = {
  PROMO: { label: 'Акции', cls: 'badge-warning' },
  NEW: { label: 'Новинки', cls: 'badge-info' },
}

// Ответ списка — плоский массив или конверт {data: [...]} (§6).
function unwrapList(res: unknown): BannerRead[] {
  if (Array.isArray(res)) return res
  const d = (res as { data?: BannerRead[] })?.data
  return Array.isArray(d) ? d : []
}

function linkLabel(b: BannerRead): string {
  if (b.link_type === 'PRODUCT') return `Товар: ${b.link_value}`
  if (b.link_type === 'NEWS') return `Новость: ${b.link_value}`
  return '—'
}

// --- Список ---
const banners = ref<BannerRead[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    banners.value = unwrapList(await request<unknown>('/api/v1/manager/banners'))
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось загрузить список баннеров')
  } finally {
    loading.value = false
  }
}

// --- Модалка создания/редактирования ---
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const submitError = ref('')

interface BannerForm {
  title: string
  subtitle: string
  position: BannerPosition
  link_type: BannerLinkType
  link_value: string
  sort: number
  is_active: boolean
  image_key: string | null
}

const emptyForm = (): BannerForm => ({
  title: '',
  subtitle: '',
  position: 'PROMO',
  link_type: 'NONE',
  link_value: '',
  sort: 0,
  is_active: true,
  image_key: null,
})

const form = ref<BannerForm>(emptyForm())

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  submitError.value = ''
  modalOpen.value = true
}

function openEdit(b: BannerRead) {
  editingId.value = b.id
  form.value = {
    title: b.title,
    subtitle: b.subtitle ?? '',
    position: b.position,
    link_type: b.link_type,
    link_value: b.link_value ?? '',
    sort: b.sort,
    is_active: b.is_active,
    image_key: b.image_key,
  }
  submitError.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false
}

// --- Загрузка изображения ---
const imageInput = ref<HTMLInputElement | null>(null)
const uploadingImage = ref(false)
const imageError = ref('')

function pickImage() {
  imageInput.value?.click()
}

async function onImageChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  imageError.value = ''
  uploadingImage.value = true
  try {
    const fd = new FormData()
    fd.append('file', f)
    const res = await request<{ key?: string } & { data?: { key?: string } }>(
      '/api/v1/manager/banners/image',
      { method: 'POST', body: fd },
    )
    const key = res.data?.key ?? res.key ?? null
    if (!key) throw new Error('Бэкенд не вернул ключ изображения')
    form.value.image_key = key
  } catch (err) {
    imageError.value = getErrorMessage(err, 'Не удалось загрузить изображение')
  } finally {
    uploadingImage.value = false
    if (imageInput.value) imageInput.value.value = ''
  }
}

// --- Сохранение ---
async function onSubmit() {
  submitError.value = ''
  if (!form.value.title.trim()) {
    submitError.value = 'Укажите заголовок баннера'
    return
  }
  const body: BannerCreate = {
    title: form.value.title.trim(),
    subtitle: form.value.subtitle.trim() || null,
    image_key: form.value.image_key,
    link_type: form.value.link_type,
    link_value: form.value.link_value.trim() || null,
    position: form.value.position,
    sort: Number(form.value.sort) || 0,
    is_active: form.value.is_active,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await request(`/api/v1/manager/banners/${editingId.value}`, { method: 'PATCH', body })
    } else {
      await request('/api/v1/manager/banners', { method: 'POST', body })
    }
    modalOpen.value = false
    await load()
  } catch (e) {
    submitError.value = getErrorMessage(e, 'Не удалось сохранить баннер')
  } finally {
    submitting.value = false
  }
}

// --- Скрыть/показать, удалить ---
const busyId = ref<string | null>(null)

async function toggleActive(b: BannerRead) {
  busyId.value = b.id
  error.value = ''
  try {
    await request(`/api/v1/manager/banners/${b.id}`, { method: 'PATCH', body: { is_active: !b.is_active } })
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось изменить баннер')
  } finally {
    busyId.value = null
  }
}

async function remove(b: BannerRead) {
  if (!window.confirm(`Удалить баннер «${b.title}»? Действие необратимо.`)) return
  busyId.value = b.id
  error.value = ''
  try {
    await request(`/api/v1/manager/banners/${b.id}`, { method: 'DELETE' })
    await load()
  } catch (e) {
    error.value = getErrorMessage(e, 'Не удалось удалить баннер')
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
        <h1 class="text-2xl font-bold">Баннеры</h1>
        <p class="text-sm text-ink-muted mt-1">
          Промо-блоки главной страницы: «Акции» и «Новинки». Показываются только активные, по полю sort.
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
      <div v-for="i in 3" :key="i" class="skeleton h-14 w-full mb-3 last:mb-0" />
    </div>

    <!-- Пусто -->
    <div v-else-if="!banners.length" class="card p-10 text-center text-ink-muted">
      <Icon name="heroicons:rectangle-stack" class="w-10 h-10 mx-auto mb-3 text-ink-faint" />
      <p>Баннеров пока нет</p>
    </div>

    <!-- Список -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
      <div v-for="b in banners" :key="b.id" class="card p-5 flex flex-col">
        <div class="flex items-start gap-4 mb-4">
          <div class="shrink-0 w-20 h-20 bg-surface rounded-card border border-border overflow-hidden flex items-center justify-center">
            <img v-if="b.image_key" :src="urlOf(b.image_key)" :alt="b.title" class="w-full h-full object-contain no-dark-invert">
            <Icon v-else name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
          </div>
          <div class="min-w-0">
            <p class="font-semibold leading-snug mb-1">{{ b.title }}</p>
            <p v-if="b.subtitle" class="text-sm text-ink-muted line-clamp-2">{{ b.subtitle }}</p>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2 mb-4">
          <span :class="POSITION_META[b.position].cls">{{ POSITION_META[b.position].label }}</span>
          <span :class="b.is_active ? 'badge-success' : 'badge-warning'">{{ b.is_active ? 'Виден' : 'Скрыт' }}</span>
          <span class="text-xs text-ink-faint">sort: {{ b.sort }}</span>
        </div>

        <p class="text-xs text-ink-muted mb-4">{{ linkLabel(b) }}</p>

        <div class="mt-auto flex flex-wrap gap-2">
          <button type="button" class="btn-outline text-sm py-1.5" :disabled="busyId === b.id" @click="openEdit(b)">
            <Icon name="heroicons:pencil-square" class="w-4 h-4" /> Изменить
          </button>
          <button type="button" class="btn-ghost text-sm py-1.5" :disabled="busyId === b.id" @click="toggleActive(b)">
            {{ b.is_active ? 'Скрыть' : 'Показать' }}
          </button>
          <button
            type="button"
            class="btn-ghost text-sm py-1.5 text-danger"
            :disabled="busyId === b.id"
            @click="remove(b)"
          >
            <span
              v-if="busyId === b.id"
              class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"
            />
            <template v-else>
              <Icon name="heroicons:trash" class="w-4 h-4" /> Удалить
            </template>
          </button>
        </div>
      </div>
    </div>

    <!-- Модалка -->
    <div v-if="modalOpen" class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" @click.self="closeModal">
      <div class="card w-full max-w-lg max-h-[90vh] overflow-y-auto p-6">
        <div class="flex items-center justify-between gap-3 mb-5">
          <h2 class="text-lg font-semibold">{{ editingId ? 'Изменить баннер' : 'Новый баннер' }}</h2>
          <button type="button" class="btn-ghost p-1.5" aria-label="Закрыть" @click="closeModal">
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>
        </div>

        <form class="grid grid-cols-1 sm:grid-cols-2 gap-4" @submit.prevent="onSubmit">
          <div class="sm:col-span-2">
            <label class="label" for="banner-title">Заголовок</label>
            <input id="banner-title" v-model="form.title" type="text" class="input py-2.5" required>
          </div>

          <div class="sm:col-span-2">
            <label class="label" for="banner-subtitle">Подзаголовок</label>
            <input id="banner-subtitle" v-model="form.subtitle" type="text" class="input py-2.5">
            <p class="text-xs text-ink-faint mt-1.5">Необязательно</p>
          </div>

          <div>
            <label class="label" for="banner-position">Позиция</label>
            <select id="banner-position" v-model="form.position" class="input py-2.5">
              <option value="PROMO">Акции</option>
              <option value="NEW">Новинки</option>
            </select>
          </div>

          <div>
            <label class="label" for="banner-sort">Порядок (sort)</label>
            <input id="banner-sort" v-model.number="form.sort" type="number" min="0" class="input py-2.5">
          </div>

          <div>
            <label class="label" for="banner-link-type">Тип ссылки</label>
            <select id="banner-link-type" v-model="form.link_type" class="input py-2.5">
              <option value="NONE">Без ссылки</option>
              <option value="PRODUCT">Товар</option>
              <option value="NEWS">Новость</option>
            </select>
          </div>

          <div>
            <label class="label" for="banner-link-value">Значение ссылки</label>
            <input
              id="banner-link-value"
              v-model="form.link_value"
              type="text"
              class="input py-2.5"
              placeholder="SKU товара или ID новости"
              :disabled="form.link_type === 'NONE'"
            >
          </div>

          <div class="sm:col-span-2">
            <label class="label">Изображение</label>
            <input
              ref="imageInput"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              class="hidden"
              @change="onImageChange"
            >
            <div class="flex items-center gap-4">
              <div class="shrink-0 w-20 h-20 bg-surface rounded-card border border-border overflow-hidden flex items-center justify-center">
                <img v-if="form.image_key" :src="urlOf(form.image_key)" alt="Превью баннера" class="w-full h-full object-contain no-dark-invert">
                <Icon v-else name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
              </div>
              <button type="button" class="btn-outline text-sm py-2" :disabled="uploadingImage" @click="pickImage">
                <span
                  v-if="uploadingImage"
                  class="w-4 h-4 border-2 border-current/40 border-t-current rounded-full animate-spin"
                />
                <Icon v-else name="heroicons:arrow-up-tray" class="w-4 h-4" />
                {{ uploadingImage ? 'Загрузка…' : 'Загрузить' }}
              </button>
            </div>
            <div v-if="imageError" class="badge-danger w-full justify-center py-2 mt-2">{{ imageError }}</div>
          </div>

          <div class="sm:col-span-2 flex items-center gap-2">
            <input id="banner-active" v-model="form.is_active" type="checkbox" class="w-4 h-4 accent-primary">
            <label for="banner-active" class="text-sm font-medium">Показывать на главной</label>
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
