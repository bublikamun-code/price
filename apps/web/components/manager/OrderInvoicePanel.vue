<script setup lang="ts">
// Блок счёта на оплату в карточке заказа менеджера (SITEMAP §«/manager/orders/
// [id]», §6 «Счета на оплату», §16 п.40). Один блок на весь жизненный цикл:
// выставление (1:1 с заказом, Idempotency-Key на операцию), смена статуса с
// If-Match по версии СЧЁТА, состояние PDF и скачивание байтами.
// Ошибки — инлайн-бейджами, как в соседних блоках менеджерки.
import type { Invoice, InvoiceStatus } from '~/domain/api/v2/invoice.schema'
import { problemMessage, toAppProblem } from '~/domain/api/v2/problem'
import {
  INVOICE_PDF_STATUS_META,
  INVOICE_STATUS_META,
  INVOICE_STATUS_OPTIONS,
  invoiceFileName,
} from '~/utils/invoice'

const props = defineProps<{
  orderId: string
  /** Статус заказа: на CANCELLED счёт не выставляется (§16 п.40 п.1). */
  orderStatus?: string
}>()

const repository = useInvoiceRepository()
const {
  activeId: downloadActiveId,
  error: downloadError,
  downloadInvoicePdf,
} = useInvoiceDownload()

const invoice = ref<Invoice | null>(null)
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const selectedStatus = ref<InvoiceStatus>('ISSUED')

const issuing = ref(false)
const savingStatus = ref(false)
const regenerating = ref(false)

// Ключ идемпотентности живёт на одну операцию «Выставить счёт»: повтор после
// сетевой ошибки обязан уйти с тем же ключом, иначе 1:1 превратится во второй
// счёт (409 INVOICE_ALREADY_EXISTS). После успеха ключ сбрасывается.
const issueKey = ref<string | null>(null)

const downloadable = computed(() => invoice.value?.pdfStatus === 'READY')
const canIssue = computed(
  () => !invoice.value && props.orderStatus !== 'CANCELLED',
)

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `invoice-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    invoice.value = await repository.getByOrder(props.orderId)
    selectedStatus.value = invoice.value.status
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось загрузить счёт')
    // 404 INVOICE_NOT_FOUND — это «счёта ещё нет», а не поломка загрузки.
    if (problem.status === 404) invoice.value = null
    else loadError.value = problemMessage(cause, 'Не удалось загрузить счёт')
  } finally {
    loading.value = false
  }
}

async function issue() {
  if (issuing.value || invoice.value) return
  if (!issueKey.value) issueKey.value = newIdempotencyKey()
  issuing.value = true
  actionError.value = ''
  try {
    invoice.value = await repository.issueForOrder(props.orderId, issueKey.value)
    selectedStatus.value = invoice.value.status
    issueKey.value = null
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось выставить счёт')
    if (problem.retryable) {
      // Сеть/5xx/429 — ключ сохраняем, повтор уйдёт с тем же ключом.
      actionError.value = `${problem.message}. Повтор безопасен: тот же ключ идемпотентности.`
    } else {
      issueKey.value = null
      actionError.value = problem.message
      await load()
    }
  } finally {
    issuing.value = false
  }
}

async function saveStatus() {
  if (!invoice.value || savingStatus.value) return
  if (selectedStatus.value === invoice.value.status) return
  const current = invoice.value
  savingStatus.value = true
  actionError.value = ''
  try {
    invoice.value = await repository.changeStatus(
      current.id,
      selectedStatus.value,
      current.version,
    )
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось изменить статус счёта')
    if (problem.code === 'STALE_RESOURCE_VERSION') {
      // Конкурирующая правка: молча перетирать нельзя — перечитываем счёт.
      actionError.value = `${problem.message}. Показываем актуальное состояние счёта.`
      selectedStatus.value = current.status
      await load()
    } else {
      actionError.value = problemMessage(cause, 'Не удалось изменить статус счёта')
      selectedStatus.value = current.status
    }
  } finally {
    savingStatus.value = false
  }
}

async function regenerate() {
  if (!invoice.value || regenerating.value) return
  const current = invoice.value
  regenerating.value = true
  actionError.value = ''
  try {
    invoice.value = await repository.regeneratePdf(current.id)
  } catch (cause) {
    const problem = toAppProblem(cause, 'Не удалось перерендерить PDF счёта')
    // 409 INVOICE_PDF_IN_PROGRESS — не ошибка: PDF уже собирается.
    actionError.value = problem.message
  } finally {
    regenerating.value = false
  }
}

function download() {
  if (!invoice.value || !downloadable.value) return
  void downloadInvoicePdf(invoice.value.id, invoiceFileName(invoice.value.number))
}

// PDF рендерит Celery (§16 п.40 п.6): пока PENDING, тихо перечитываем счёт —
// пользователь не должен жать «Обновить», чтобы получить готовый файл.
let pollTimer: ReturnType<typeof setTimeout> | null = null
const POLL_ATTEMPTS = 20
const POLL_INTERVAL_MS = 3000
let pollAttempts = 0

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  if (invoice.value?.pdfStatus !== 'PENDING') return
  if (pollAttempts >= POLL_ATTEMPTS) return
  pollTimer = setTimeout(async () => {
    pollTimer = null
    pollAttempts += 1
    await load()
    schedulePoll()
  }, POLL_INTERVAL_MS)
}

onMounted(async () => {
  await load()
  schedulePoll()
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<template>
  <div class="mb-5 border border-border bg-surface p-4" data-testid="manager-invoice-panel">
    <div class="mb-3 flex items-center justify-between gap-3">
      <h3 class="font-semibold">Счёт на оплату</h3>
      <button
        v-if="invoice"
        type="button"
        class="btn-ghost min-h-9 px-2 text-xs"
        :disabled="loading"
        data-testid="manager-invoice-reload"
        @click="load"
      >
        <Icon name="heroicons:arrow-path" class="w-3.5 h-3.5" /> Обновить
      </button>
    </div>

    <p v-if="loading" class="text-sm text-ink-faint">Загрузка счёта…</p>

    <div v-else-if="loadError" class="flex flex-wrap items-center gap-2">
      <span class="badge-danger" role="alert">{{ loadError }}</span>
      <button type="button" class="btn-outline min-h-9 px-2 text-xs" @click="load">Повторить</button>
    </div>

    <!-- Счёта нет -->
    <div v-else-if="!invoice" data-testid="manager-invoice-empty">
      <p class="text-sm text-ink-muted">
        Счёт 1:1 с заказом: выставляется один раз, суммы замораживаются на момент выставления.
      </p>
      <button
        v-if="canIssue"
        type="button"
        class="btn-primary mt-3 min-h-11"
        :disabled="issuing"
        data-testid="manager-invoice-issue"
        @click="issue"
      >
        <span
          v-if="issuing"
          class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"
        />
        <Icon v-else name="heroicons:document-text" class="w-4 h-4" />
        {{ issuing ? 'Выставляем…' : 'Выставить счёт' }}
      </button>
      <p v-else class="mt-3 text-sm text-ink-muted">
        Заказ отменён — счёт по нему выставить нельзя.
      </p>
    </div>

    <!-- Счёт есть -->
    <div v-else data-testid="manager-invoice-card">
      <div class="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Номер</span>
          <span class="numeric font-medium sm:mt-1 sm:block">{{ invoice.number }}</span>
        </div>
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Дата выставления</span>
          <span class="font-medium sm:mt-1 sm:block">{{ formatDateTime(invoice.issuedAt) }}</span>
        </div>
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Сумма</span>
          <span class="numeric font-medium sm:mt-1 sm:block">
            {{ formatMoney(invoice.total.amount, invoice.total.currency) }}
          </span>
        </div>
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Срок оплаты</span>
          <span class="font-medium sm:mt-1 sm:block">{{ invoice.dueAt ? formatDate(invoice.dueAt) : '—' }}</span>
        </div>
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Покупатель</span>
          <span class="font-medium sm:mt-1 sm:block">{{ invoice.buyer.legalName }}</span>
        </div>
        <div class="flex justify-between gap-4 sm:block">
          <span class="text-ink-muted">Продавец</span>
          <span class="font-medium sm:mt-1 sm:block">{{ invoice.seller.legalName }}</span>
        </div>
      </div>

      <p v-if="invoice.buyer.taxId" class="mt-3 text-xs text-ink-faint">
        УНП покупателя: <span class="numeric">{{ invoice.buyer.taxId }}</span>
        <template v-if="!invoice.buyer.legalAddress || !invoice.buyer.bank?.account">
          — реквизиты заполняются в карточке организации и попадут в следующий рендер PDF.
        </template>
      </p>

      <!-- Статус счёта -->
      <div class="mt-4 border-t border-border pt-3">
        <div class="flex flex-wrap items-center gap-3">
          <label class="text-sm text-ink-muted" for="invoice-status">Статус счёта:</label>
          <select id="invoice-status" v-model="selectedStatus" class="input min-h-11 w-auto" data-testid="manager-invoice-status">
            <option v-for="option in INVOICE_STATUS_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <button
            type="button"
            class="btn-primary min-h-11"
            :disabled="savingStatus || selectedStatus === invoice.status"
            data-testid="manager-invoice-status-save"
            @click="saveStatus"
          >
            <span
              v-if="savingStatus"
              class="w-4 h-4 border-2 border-white/40 border-t-white rounded-sm animate-spin"
            />
            <Icon v-else name="heroicons:check" class="w-4 h-4" />
            Применить
          </button>
          <UiStatusBadge
            :tone="INVOICE_STATUS_META[invoice.status].tone"
            :label="INVOICE_STATUS_META[invoice.status].label"
            dot
            data-testid="manager-invoice-status-badge"
          />
        </div>
        <p class="mt-1 text-xs text-ink-faint">
          Статус счёта не меняет статус заказа. Версия счёта {{ invoice.version }} сверяется при сохранении.
        </p>
      </div>

      <!-- PDF -->
      <div class="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <UiStatusBadge
          :tone="INVOICE_PDF_STATUS_META[invoice.pdfStatus].tone"
          :label="`PDF: ${INVOICE_PDF_STATUS_META[invoice.pdfStatus].label}`"
          data-testid="manager-invoice-pdf-status"
        />
        <button
          type="button"
          class="btn-outline min-h-11"
          :disabled="!downloadable || downloadActiveId !== null"
          :title="downloadable ? '' : 'PDF ещё не готов'"
          data-testid="manager-invoice-download"
          @click="download"
        >
          <span
            v-if="downloadActiveId !== null"
            class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-sm animate-spin"
          />
          <Icon v-else name="heroicons:document-arrow-down" class="w-4 h-4" />
          {{ downloadActiveId !== null ? 'Скачиваем…' : 'Скачать счёт' }}
        </button>
        <button
          v-if="invoice.pdfStatus === 'FAILED'"
          type="button"
          class="btn-outline min-h-11"
          :disabled="regenerating"
          data-testid="manager-invoice-pdf-regenerate"
          @click="regenerate"
        >
          <span
            v-if="regenerating"
            class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-sm animate-spin"
          />
          <Icon v-else name="heroicons:arrow-path" class="w-4 h-4" />
          {{ regenerating ? 'Отправляем…' : 'Перерендерить PDF' }}
        </button>
        <p v-if="invoice.pdfStatus === 'PENDING'" class="text-xs text-ink-muted">
          PDF собирается в фоне — скачивание станет доступно через несколько секунд.
        </p>
        <p v-else-if="invoice.pdfStatus === 'FAILED'" class="text-xs text-danger">
          Рендер счёта не удался. После правки реквизитов нажмите «Перерендерить PDF».
        </p>
      </div>
    </div>

    <p v-if="actionError" class="badge-danger mt-3" role="alert" data-testid="manager-invoice-error">
      {{ actionError }}
    </p>
    <p v-if="downloadError" class="badge-danger mt-3" role="alert">{{ downloadError }}</p>
  </div>
</template>
