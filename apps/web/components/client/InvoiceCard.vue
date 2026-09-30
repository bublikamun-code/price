<script setup lang="ts">
// Карточка счёта на оплату в деталях заказа клиента (SITEMAP §«/orders/[id]»
// п.5, §6 «Счета на оплату», §16 п.40). Только чтение: статус счёта переключает
// менеджер, клиент видит номер, дату, сумму, статус и скачивает PDF байтами
// (никогда presigned — §16 п.37). Если счёта нет — блок не показывается вовсе.
import type { Invoice } from '~/domain/api/v2/invoice.schema'
import { INVOICE_PDF_STATUS_META, INVOICE_STATUS_META, invoiceFileName } from '~/utils/invoice'

const props = defineProps<{ invoice: Invoice }>()

const { activeId, error, downloadInvoicePdf } = useInvoiceDownload()

const downloadable = computed(() => props.invoice.pdfStatus === 'READY')
const busy = computed(() => activeId.value !== null)

function download() {
  if (!downloadable.value || busy.value) return
  void downloadInvoicePdf(props.invoice.id, invoiceFileName(props.invoice.number))
}
</script>

<template>
  <section
    class="border-b border-border pb-6"
    aria-labelledby="order-invoice-title"
    data-testid="order-invoice-card"
  >
    <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-wider text-ink-muted">Оплата</p>
        <h2 id="order-invoice-title" class="mt-1 text-lg font-bold text-ink">Счёт на оплату</h2>
      </div>
      <UiStatusBadge
        :tone="INVOICE_STATUS_META[invoice.status].tone"
        :label="INVOICE_STATUS_META[invoice.status].label"
        dot
        data-testid="order-invoice-status"
      />
    </div>

    <dl class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      <div class="flex justify-between gap-4 sm:block">
        <dt class="text-ink-muted">Номер</dt>
        <dd class="numeric font-medium text-ink sm:mt-1">{{ invoice.number }}</dd>
      </div>
      <div class="flex justify-between gap-4 sm:block">
        <dt class="text-ink-muted">Дата выставления</dt>
        <dd class="font-medium text-ink sm:mt-1">{{ formatDateTime(invoice.issuedAt) }}</dd>
      </div>
      <div class="flex justify-between gap-4 sm:block">
        <dt class="text-ink-muted">Сумма к оплате</dt>
        <dd class="numeric font-medium text-ink sm:mt-1">
          {{ formatMoney(invoice.total.amount, invoice.total.currency) }}
        </dd>
      </div>
      <div class="flex justify-between gap-4 sm:block">
        <dt class="text-ink-muted">Срок оплаты</dt>
        <dd class="font-medium text-ink sm:mt-1">{{ invoice.dueAt ? formatDate(invoice.dueAt) : 'не указан' }}</dd>
      </div>
    </dl>

    <div class="mt-4 flex flex-wrap items-center gap-3">
      <UiButton
        variant="outline"
        size="touch"
        :loading="busy"
        :disabled="!downloadable || busy"
        :title="downloadable ? '' : 'PDF счёта ещё готовится'"
        data-testid="order-invoice-download"
        @click="download"
      >
        <template #leading>
          <Icon name="heroicons:document-arrow-down" class="size-4" />
        </template>
        {{ busy ? 'Скачиваем…' : 'Скачать PDF' }}
      </UiButton>
      <UiStatusBadge
        :tone="INVOICE_PDF_STATUS_META[invoice.pdfStatus].tone"
        :label="`PDF: ${INVOICE_PDF_STATUS_META[invoice.pdfStatus].label}`"
        data-testid="order-invoice-pdf-status"
      />
      <p v-if="!downloadable" class="text-xs leading-5 text-ink-muted">
        PDF счёта ещё готовится. Кнопка станет активной, как только файл будет сформирован.
      </p>
    </div>

    <p v-if="invoice.dueAt && invoice.status === 'ISSUED'" class="mt-3 text-xs leading-5 text-ink-muted">
      Оплатите счёт до {{ formatDate(invoice.dueAt) }} и сообщите менеджеру — он отметит статус «Оплачен».
    </p>

    <UiErrorState
      v-if="error"
      class="mt-4"
      title="Счёт не скачан"
      :description="error"
      data-testid="order-invoice-download-error"
    />
  </section>
</template>
