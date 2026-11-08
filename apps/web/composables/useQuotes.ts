// Коммерческие предложения (Э8): репозиторий v2 для JSON-операций
// (менеджерские create/edit/send/delete + PDF-рендер, клиентские лента/
// accept/reject). Скачивание PDF байтами идёт через внедрённый транспорт —
// тот же паттерн, что в useInvoice/useInvoiceDownload.
import { createQuoteRepository } from '~/domain/quote/quote.repository'
import { saveBlobToFile } from './useInvoiceDownload'

export function useQuotes() {
  const { request } = useApi()

  const repository = createQuoteRepository(useApiV2(), {
    fetch: (path) => request<Blob>(path, { responseType: 'blob' }),
    save: saveBlobToFile,
  })

  // Скачивание PDF: защита от параллельных кликов (один КП — одно
  // скачивание), ошибка действия живёт здесь, состояние страницы не трогаем.
  const activeId = ref<string | null>(null)
  const error = ref('')

  async function downloadPdf(quoteId: string, fileName: string): Promise<boolean> {
    if (activeId.value) return false
    activeId.value = quoteId
    error.value = ''
    try {
      await repository.downloadPdf(quoteId, fileName)
      return true
    } catch (e) {
      error.value = getErrorMessage(e, 'Не удалось скачать КП')
      return false
    } finally {
      activeId.value = null
    }
  }

  return { repository, activeId, error, downloadPdf }
}
