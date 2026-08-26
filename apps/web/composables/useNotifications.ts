// In-app уведомления: счётчик непрочитанных для колокольчика в AppHeader.
// Module-level ref (как useCart) — общий бейдж между шапкой и страницей /notifications.
// Полный список/чтение — на самой странице; здесь бейдж + SSE-стрим с poll-fallback.
// См. ARCHITECTURE_PLAN §16 п.26, SITEMAP §6.
import type { NotificationItem, NotificationsPage } from '~/types/api'

const unreadCount = ref(0)
const POLL_INTERVAL_MS = 60_000

let pollTimer: ReturnType<typeof setInterval> | null = null
let stream: EventSource | null = null
let streamHadDrop = false // был разрыв: после reconnect синхронизируем бейдж через refresh()

export function useNotifications() {
  const { request } = useApi()

  /** Обновить бейдж: meta.unread_count (свои непрочитанные). Ошибки — тихо. */
  async function refresh(): Promise<void> {
    try {
      const res = await request<NotificationsPage>('/api/v1/notifications', {
        query: { page: 1, per_page: 1 },
      })
      unreadCount.value = res.meta?.unread_count ?? 0
    } catch {
      // Тихо: бейдж не критичен (401 разрулит useApi).
    }
  }

  /** Poll-fallback (60 с), только на клиенте; тики без сессии пропускаются. Идемпотентен. */
  function startPolling() {
    if (pollTimer || !import.meta.client) return
    const auth = useAuth() // стор-синглтон: состояние живёт всё время приложения
    pollTimer = setInterval(() => {
      if (auth.isAuthenticated) refresh()
    }, POLL_INTERVAL_MS)
  }

  /**
   * SSE-стрим бейджа (§16 п.26). Same-origin EventSource — cookie access_token
   * идёт автоматически (заголовки EventSource не умеет, потому и cookie-auth).
   * Именованное событие `notification`; heartbeat-комментарий `: ping`
   * браузер пропускает сам.
   *
   * Ошибки: сетевой drop (readyState CONNECTING) → авто-reconnect самим
   * EventSource, после onopen — refresh(); фатальный отказ (401 и т.п.,
   * readyState CLOSED, reconnect не будет) → close + возврат на poll-fallback.
   */
  function startStream() {
    if (!import.meta.client || stream) return
    stream = new EventSource('/api/v1/notifications/stream')

    stream.addEventListener('notification', (ev) => {
      try {
        const n = JSON.parse((ev as MessageEvent<string>).data) as Partial<NotificationItem>
        if (typeof n.id === 'string') unreadCount.value++
      } catch {
        // Битый payload — игнорируем; точное значение доберёт refresh().
      }
    })

    stream.onopen = () => {
      if (streamHadDrop) {
        streamHadDrop = false
        refresh() // пока висел drop, события могли потеряться — синхронизируем бейдж
      }
    }

    stream.onerror = () => {
      if (!stream) return
      if (stream.readyState === EventSource.CLOSED) {
        // Сервер отказал в коннекте (401/ошибка) — авто-reconnect не будет: уходим в pull.
        stream.close()
        stream = null
        streamHadDrop = false
        startPolling()
      } else {
        // CONNECTING: EventSource переподключится сам.
        streamHadDrop = true
      }
    }
  }

  /** Закрыть стрим (unmount шапки / logout). Poll-fallback не трогаем: идемпотентен. */
  function stopStream() {
    stream?.close()
    stream = null
    streamHadDrop = false
  }

  return { unreadCount, refresh, startPolling, startStream, stopStream }
}
