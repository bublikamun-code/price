// Скачивание PDF счёта на оплату (§6 «Счета на оплату», §16 п.40):
// GET /api/v2/orders/invoices/{invoiceId}/download отдаёт байты (никогда
// presigned — урок mixed-content 27.09, §16 п.37) → blob → objectURL →
// <a download>. Паттерн тот же, что в useDocumentDownload: $api с
// credentials: 'include' (кука авторизации) + безопасное имя файла из номера
// счёта (`СЧ-2026-000042`).
import { createInvoiceRepository } from '~/domain/invoice/invoice.repository'

/** Сохраняет blob как файл; URL объекта освобождается в любом случае. */
export function saveBlobToFile(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function useInvoiceDownload() {
  const { request } = useApi()
  const activeId = ref<string | null>(null)
  const error = ref('')

  const repository = createInvoiceRepository(useApiV2(), {
    fetch: (path) => request<Blob>(path, { responseType: 'blob' }),
    save: saveBlobToFile,
  })

  async function downloadInvoicePdf(invoiceId: string, fileName: string): Promise<void> {
    // Защита от параллельных кликов: один заказ — одно скачивание, иначе
    // браузер блокирует серию «автоматических» загрузок.
    if (activeId.value) return
    activeId.value = invoiceId
    error.value = ''
    try {
      await repository.downloadPdf(invoiceId, fileName)
    } catch (e) {
      error.value = getErrorMessage(e, 'Не удалось скачать счёт')
    } finally {
      activeId.value = null
    }
  }

  return { activeId, error, downloadInvoicePdf }
}
