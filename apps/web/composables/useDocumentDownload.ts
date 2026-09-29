// Скачивание PDF-документа товара (§16 п.38): GET /catalog/products/{productId}/
// documents/{documentId}/download отдаёт байты (не presigned) → blob → сохранение
// файла. Паттерн тот же, что в useXlsxExport: $api с credentials: 'include'
// (кука авторизации) + имя файла из контракта (document.fileName).
export function useDocumentDownload() {
  const { request } = useApi()
  const activeId = ref<string | null>(null)
  const error = ref('')

  async function downloadProductDocument(
    productId: string,
    documentId: string,
    fileName = 'document.pdf',
  ): Promise<void> {
    if (activeId.value) return
    activeId.value = documentId
    error.value = ''
    try {
      const blob = await request<Blob>(
        `/api/v2/catalog/products/${productId}/documents/${documentId}/download`,
        { responseType: 'blob' },
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // Резервируем только опасное: кириллица и цифры в именах документов валидны.
      a.download = fileName.replace(/[^\p{L}\p{N}._-]+/gu, '_') || 'document.pdf'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      error.value = getErrorMessage(e, 'Не удалось скачать документ')
    } finally {
      activeId.value = null
    }
  }

  return { activeId, error, downloadProductDocument }
}
