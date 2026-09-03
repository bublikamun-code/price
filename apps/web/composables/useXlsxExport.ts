// Экспорт заявки в Excel (§6): GET /orders/{id}/export.xlsx → blob → скачивание.

export function useXlsxExport() {
  const { request } = useApi()
  const activeId = ref<string | null>(null)
  const error = ref('')

  async function exportOrderXlsx(orderId: string, fileName = 'order.xlsx'): Promise<void> {
    if (activeId.value) return
    activeId.value = orderId
    error.value = ''
    try {
      const blob = await request<Blob>(`/api/v1/orders/${orderId}/export.xlsx`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName.replace(/[^\w.-]+/g, '_') || 'order.xlsx'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      error.value = getErrorMessage(e, 'Не удалось скачать Excel')
    } finally {
      activeId.value = null
    }
  }

  return { activeId, error, exportOrderXlsx }
}
