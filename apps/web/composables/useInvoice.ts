// Счёт на оплату (§6 «Счета на оплату», §16 п.40): репозиторий v2 для
// JSON-операций (выставление, смена статуса, перерендер PDF, реквизиты
// организации). Скачивание PDF байтами живёт в useInvoiceDownload.
import { createInvoiceRepository } from '~/domain/invoice/invoice.repository'
import { saveBlobToFile } from './useInvoiceDownload'

export function useInvoiceRepository() {
  const { request } = useApi()
  return createInvoiceRepository(useApiV2(), {
    fetch: (path) => request<Blob>(path, { responseType: 'blob' }),
    save: saveBlobToFile,
  })
}
