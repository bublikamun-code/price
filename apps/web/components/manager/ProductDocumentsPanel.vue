<script setup lang="ts">
// Панель документов товара/серии (этап 3 «Документы на товар», §16 п.38):
// список + загрузка PDF (CERTIFICATE|DATASHEET, срок опционален) + удаление
// с подтверждением. Используется в модалке товара (/manager/catalog) и в
// модалке серии (/manager/brands). Ошибки API — инлайн-бейджи, как в соседних
// формах менеджерки. Внутри формы товара панели <form> быть не может (вложенные
// формы ломают SSR) — сабмит по кнопке type="button".
import type { DocumentType, ProductDocument } from '~/domain/api/v2/documents.schema'
import { createDocumentsRepository } from '~/domain/documents/documents.repository'

const props = defineProps<{
  scope: 'product' | 'series'
  targetId: string
}>()

const repository = createDocumentsRepository(useApiV2())

// Лимит зеркалит files_max_mb на бэке (app/core/config.py).
const MAX_PDF_BYTES = 200 * 1024 * 1024

const loading = ref(false)
const loadError = ref('')
const docs = ref<ProductDocument[]>([])

const pickedFile = ref<File | null>(null)
const docType = ref<DocumentType>('CERTIFICATE')
const validUntil = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')

const confirmingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const deleteError = ref('')

const scopeLabel = computed(() => (props.scope === 'product' ? 'товара' : 'серии'))

async function load() {
  if (!props.targetId) return
  loading.value = true
  loadError.value = ''
  try {
    docs.value =
      props.scope === 'product'
        ? await repository.listForProduct(props.targetId)
        : await repository.listForSeries(props.targetId)
  } catch (e) {
    loadError.value = getErrorMessage(e, 'Не удалось загрузить список документов')
  } finally {
    loading.value = false
  }
}

function onFilePick(event: Event) {
  const input = event.target as HTMLInputElement
  pickedFile.value = input.files?.[0] ?? null
  uploadError.value = ''
}

function resetForm() {
  pickedFile.value = null
  validUntil.value = ''
  if (fileInput.value) fileInput.value.value = '' // чтобы можно было выбрать тот же файл повторно
}

async function submitUpload() {
  if (uploading.value || !props.targetId) return
  const file = pickedFile.value
  if (!file) {
    uploadError.value = 'Выберите PDF-файл'
    return
  }
  if (!/\.pdf$/i.test(file.name)) {
    uploadError.value = 'Допустим только PDF'
    return
  }
  if (file.size > MAX_PDF_BYTES) {
    uploadError.value = 'Файл больше 200 МБ'
    return
  }
  uploadError.value = ''
  uploading.value = true
  try {
    const input = { file, type: docType.value, validUntil: validUntil.value || null }
    const created =
      props.scope === 'product'
        ? await repository.uploadForProduct(props.targetId, input)
        : await repository.uploadForSeries(props.targetId, input)
    docs.value = [...docs.value, created]
    resetForm()
  } catch (e) {
    uploadError.value = getErrorMessage(e, 'Не удалось загрузить документ')
  } finally {
    uploading.value = false
  }
}

function confirmRemove(doc: ProductDocument) {
  deleteError.value = ''
  confirmingId.value = confirmingId.value === doc.id ? null : doc.id
}

async function doRemove(doc: ProductDocument) {
  if (deletingId.value) return
  deletingId.value = doc.id
  deleteError.value = ''
  try {
    await repository.remove(doc.id)
    docs.value = docs.value.filter((item) => item.id !== doc.id)
    confirmingId.value = null
  } catch (e) {
    deleteError.value = getErrorMessage(e, 'Не удалось удалить документ')
  } finally {
    deletingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="border border-border p-3" data-testid="manager-documents-panel">
    <div class="flex items-center justify-between gap-2">
      <h4 class="text-sm font-semibold">Документы {{ scopeLabel }} (PDF)</h4>
      <button type="button" class="btn-ghost min-h-9 px-2 text-xs" :disabled="loading" @click="load">
        <Icon name="heroicons:arrow-path" class="w-3.5 h-3.5" /> Обновить
      </button>
    </div>

    <p v-if="loading" class="mt-2 text-xs text-ink-faint">Загрузка списка…</p>
    <div v-else-if="loadError" class="mt-2 flex flex-wrap items-center gap-2">
      <span class="badge-danger">{{ loadError }}</span>
      <button type="button" class="btn-ghost min-h-9 px-2 text-xs" @click="load">Повторить</button>
    </div>

    <ul v-else-if="docs.length" class="mt-2 border border-border">
      <li
        v-for="doc in docs"
        :key="doc.id"
        class="flex flex-wrap items-center gap-2 border-b border-border px-2 py-2 text-sm last:border-b-0"
        :data-testid="`manager-document-${doc.id}`"
      >
        <UiStatusBadge :tone="doc.type === 'CERTIFICATE' ? 'info' : 'neutral'" :label="doc.type === 'CERTIFICATE' ? 'Сертификат' : 'Даташит'" />
        <span class="min-w-0 flex-1 truncate" :title="doc.fileName">{{ doc.fileName }}</span>
        <span v-if="doc.validUntil" class="text-xs" :class="doc.isExpired ? 'text-danger' : 'text-ink-muted'">
          {{ doc.isExpired ? 'истёк' : 'до' }} {{ formatDate(doc.validUntil) }}
        </span>
        <template v-if="confirmingId === doc.id">
          <span class="text-xs text-danger">Удалить документ?</span>
          <button
            type="button"
            class="btn-outline min-h-9 px-2 text-xs text-danger"
            :disabled="deletingId === doc.id"
            :data-testid="`manager-document-delete-confirm-${doc.id}`"
            @click="doRemove(doc)"
          >
            <span v-if="deletingId === doc.id" class="w-3 h-3 border-2 border-danger/40 border-t-danger rounded-sm animate-spin" />
            {{ deletingId === doc.id ? 'Удаление…' : 'Удалить' }}
          </button>
          <button type="button" class="btn-ghost min-h-9 px-2 text-xs" @click="confirmingId = null">Отмена</button>
        </template>
        <button
          v-else
          type="button"
          class="btn-ghost min-h-9 px-2 text-xs text-danger"
          :data-testid="`manager-document-delete-${doc.id}`"
          @click="confirmRemove(doc)"
        >
          <Icon name="heroicons:trash" class="w-3.5 h-3.5" /> Удалить
        </button>
      </li>
    </ul>
    <p v-else class="mt-2 text-xs text-ink-faint">Документов пока нет.</p>

    <p v-if="deleteError" class="badge-danger mt-2">{{ deleteError }}</p>

    <!-- Загрузка нового документа (без <form>: панель живёт внутри формы товара) -->
    <div class="mt-3 border-t border-border pt-3">
      <p class="label mb-2">Загрузить документ</p>
      <div class="space-y-2">
        <div>
          <label class="label sr-only" :for="`doc-file-${targetId}`">PDF-файл</label>
          <input
            :id="`doc-file-${targetId}`"
            ref="fileInput"
            type="file"
            accept=".pdf,application/pdf"
            class="input file:mr-3 file:border-0 file:bg-transparent file:px-0 file:text-xs file:font-semibold file:text-primary"
            :data-testid="`manager-document-file-${scope}`"
            @change="onFilePick"
          >
        </div>
        <div class="grid gap-2 sm:grid-cols-2">
          <div>
            <label class="label" :for="`doc-type-${targetId}`">Тип</label>
            <select
              :id="`doc-type-${targetId}`"
              v-model="docType"
              class="input"
              :data-testid="`manager-document-type-${scope}`"
            >
              <option value="CERTIFICATE">Сертификат</option>
              <option value="DATASHEET">Даташит</option>
            </select>
          </div>
          <div>
            <label class="label" :for="`doc-valid-${targetId}`">Действует до</label>
            <input
              :id="`doc-valid-${targetId}`"
              v-model="validUntil"
              type="date"
              class="input"
              :data-testid="`manager-document-valid-${scope}`"
            >
          </div>
        </div>
        <button
          type="button"
          class="btn-primary min-h-11 w-full sm:w-auto"
          :disabled="uploading"
          :data-testid="`manager-document-upload-${scope}`"
          @click="submitUpload"
        >
          <span v-if="uploading" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin" />
          <Icon v-else name="heroicons:arrow-up-tray" class="w-4 h-4" />
          {{ uploading ? 'Загрузка…' : 'Загрузить документ' }}
        </button>
      </div>
      <p v-if="uploadError" class="badge-danger mt-2" role="alert">{{ uploadError }}</p>
      <p v-else class="text-xs text-ink-faint mt-2">
        Документы серии наследуют все товары серии; срок «Действует до» можно не указывать.
      </p>
    </div>
  </div>
</template>
