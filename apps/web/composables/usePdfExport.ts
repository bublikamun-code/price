// Экспорт заявки в PDF (§6): POST /orders/{id}/pdf → фоновый job → poll → открыть url.

const POLL_MS = 2000
const MAX_POLLS = 60

interface PdfStart {
  job_id: string
}

interface PdfJob {
  status: string
  url?: string
  error?: string
}

export function usePdfExport() {
  const { request } = useApi()
  const activeId = ref<string | null>(null)
  const error = ref('')
  // Таймер опроса: сбрасывается при размонтировании компонента, чтобы
  // поллинг не продолжался после ухода со страницы (P2 §3.3).
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  if (getCurrentInstance()) {
    onUnmounted(() => {
      if (pollTimer !== null) clearTimeout(pollTimer)
      pollTimer = null
    })
  }

  async function exportOrderPdf(orderId: string): Promise<void> {
    if (activeId.value) return
    activeId.value = orderId
    error.value = ''
    try {
      const started = await request<PdfStart>(`/api/v1/orders/${orderId}/pdf`, { method: 'POST' })
      await poll(started.job_id)
    } catch (e) {
      error.value = getErrorMessage(e, 'Не удалось запустить экспорт PDF')
      activeId.value = null
    }
  }

  function poll(jobId: string): Promise<void> {
    return new Promise((resolve) => {
      let attempts = 0
      const tick = async () => {
        attempts++
        let job: PdfJob
        try {
          job = await request<PdfJob>(`/api/v1/orders/export/${jobId}`)
        } catch (e) {
          error.value = getErrorMessage(e, 'Не удалось получить статус экспорта')
          activeId.value = null
          return resolve()
        }
        if (job.status === 'DONE' && job.url) {
          window.open(job.url, '_blank')
          activeId.value = null
          return resolve()
        }
        if (job.status === 'FAILED') {
          error.value = job.error || 'Не удалось сформировать PDF'
          activeId.value = null
          return resolve()
        }
        if (attempts >= MAX_POLLS) {
          error.value = 'PDF готовится слишком долго, попробуйте позже'
          activeId.value = null
          return resolve()
        }
        pollTimer = setTimeout(tick, POLL_MS)
      }
      tick()
    })
  }

  return { activeId, error, exportOrderPdf }
}
