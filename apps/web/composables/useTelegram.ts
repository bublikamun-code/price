// Composable для Telegram Mini App (§16): доступ к Telegram.WebApp, initData,
// вход по коду связки. На сервере (и вне Telegram) webApp() === null.

/** Доступные поля Telegram WebApp, которые использует портал. */
interface TelegramWebAppLike {
  initData: string
  ready: () => void
  expand: () => void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebAppLike }
  }
}

export interface TelegramAuthResult {
  ok: boolean
  kind: 'success' | 'error'
  message?: string
}

export function useTelegram() {
  const auth = useAuth()

  /** Telegram WebApp или null (сервер / обычный браузер). */
  function webApp(): TelegramWebAppLike | null {
    if (!import.meta.client) return null
    return window.Telegram?.WebApp ?? null
  }

  /** Подписанные initData текущего пользователя Telegram; '' вне Mini App. */
  function initData(): string {
    return webApp()?.initData ?? ''
  }

  /** Ждём появления initData (WebView инжектит Telegram JS не сразу). */
  function waitForInitData(timeoutMs = 4000): Promise<string> {
    return new Promise((resolve) => {
      const initial = initData()
      if (initial) return resolve(initial)
      const startedAt = Date.now()
      const timer = setInterval(() => {
        const data = initData()
        if (data) {
          clearInterval(timer)
          resolve(data)
        } else if (Date.now() - startedAt >= timeoutMs) {
          clearInterval(timer)
          resolve('')
        }
      }, 250)
    })
  }

  /** Сигнал Telegram о готовности интерфейса (скрыть сплэш WebView). */
  function signalReady(): void {
    if (!import.meta.client) return
    webApp()?.ready()
    webApp()?.expand()
  }

  /** Вход в портал из Mini App: initData + код связки → токены + профиль. */
  async function telegramAuth(linkCode: string): Promise<TelegramAuthResult> {
    if (import.meta.server) {
      return { ok: false, kind: 'error', message: 'Mini App доступен только в Telegram' }
    }
    // Через useApi, а не сырой $fetch: plugins/api.ts добавляет X-CSRF-Token на
    // мутирующие запросы, а useApi.request переживает 401 единым refresh'ем.
    // С POST /auth/login было то же самое — этот выход оставался последним
    // мутирующим запросом вне общей обвязки.
    const { request } = useApi()
    try {
      const pair = await request<{ access_token: string; refresh_token?: string }>(
        '/api/m/v1/auth/telegram',
        {
          method: 'POST',
          body: { init_data: initData(), link_code: linkCode },
          credentials: 'include',
        },
      )
      auth.applyTokens(pair)
      await auth.fetchMe()
      return { ok: true, kind: 'success' }
    } catch (e) {
      return {
        ok: false,
        kind: 'error',
        message: getErrorMessage(e, 'Не удалось войти через Telegram'),
      }
    }
  }

  return { webApp, initData, waitForInitData, signalReady, telegramAuth }
}
