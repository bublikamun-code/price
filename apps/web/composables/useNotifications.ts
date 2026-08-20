// In-app уведомления: счётчик непрочитанных для колокольчика в AppHeader.
// Module-level ref (как useCart) — общий бейдж между шапкой и страницей /notifications.
// Полный список/чтение — на самой странице; здесь только бейдж + поллинг. См. SITEMAP §6.
import type { NotificationsPage } from '~/types/api'

const unreadCount = ref(0)
const POLL_INTERVAL_MS = 60_000
let polling = false

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

  /** Поллинг каждые 60 с, только на клиенте; тики без сессии пропускаются. */
  function startPolling() {
    if (polling || !import.meta.client) return
    polling = true
    const auth = useAuth() // стор-синглтон: состояние живёт всё время приложения
    setInterval(() => {
      if (auth.isAuthenticated) refresh()
    }, POLL_INTERVAL_MS)
  }

  return { unreadCount, refresh, startPolling }
}
