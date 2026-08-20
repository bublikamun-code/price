// Composable авторизации (Этап 2). Реальные вызовы /api/v1/auth/*.
// Стор хранит user/access token; refresh остаётся только в серверной httpOnly cookie.
// Cookie-refs регистрирует плагин auth.session.ts.
// (создание useCookie в контексте плагина надёжно и на сервере, и на клиенте;
// прямой wpis — без гонки таймингов watcher'ов).
// См. ARCHITECTURE_PLAN.md §6, §11.
import { defineStore } from 'pinia'
import type { TokenPair, UserPublic, UserRole } from '~/types/api'

export interface AuthUser {
  id: string
  email: string
  name: string // ← маппится из бэкендовского full_name
  role: UserRole
  displayCurrency: string
  company?: string | null
  phone?: string | null
  // Дайджест изменения цен (in-app уведомления).
  priceDigestEnabled: boolean
  priceDigestSources: string[] // 'cart' | 'favorite' | 'orders'
  // Согласие на обработку ПДн (SITEMAP /consent). false → клиент ведётся на /consent.
  consent_accepted: boolean
}

/** Тело PATCH /api/v1/auth/me (минимум одно поле). */
export interface UserMePatch {
  display_currency?: string
  price_digest_enabled?: boolean
  price_digest_sources?: string[]
  consent_accepted?: boolean
}

/** Cookie-refs, регистрируемые плагином auth.session.ts. */
export interface CookieStore {
  tokenC: { value: string | null }
  userC: { value: AuthUser | null }
}

/** baseURL API: на сервере — внутренний, на клиенте — публичный. */
function apiBaseURL(): string {
  const config = useRuntimeConfig()
  return import.meta.server ? config.apiBase : config.public.apiBase
}

function csrfHeaders(): Record<string, string> {
  const csrfToken = useCookie<string | null>('csrf_token').value
  return csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
}

const COOKIE_MAX_AGE = {
  token: 60 * 60, // 1 ч
  user: 60 * 60 * 24, // 1 день
}

/**
 * Немедленная запись cookie в document.cookie на клиенте.
 * useCookie на клиенте пишет отложенно (через хуки page:finish); при серверном
 * рендере целевого маршрута сразу после navigateTo cookie может ещё не попасть
 * в document.cookie → middleware его не найдёт. Прямая запись решает гонку.
 */
function persistCookie(name: string, value: string | null, maxAge: number): void {
  if (!import.meta.client) return
  if (value === null) {
    document.cookie = `${name}=; path=/; max-age=0; samesite=lax`
  } else {
    document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const token = ref<string | null>(null)

  // cookie-refs подключаются плагином; до этого просто храним в состоянии.
  let cookies: CookieStore | null = null

  const isAuthenticated = computed(() => !!user.value && !!token.value)
  const isClient = computed(() => user.value?.role === 'CLIENT')
  const isManager = computed(() => user.value?.role === 'MANAGER')

  /** Вызывается из plugins/auth.session.ts один раз при старте. */
  function registerCookies(c: CookieStore) {
    cookies = c
  }

  function applyUser(u: UserPublic | null) {
    if (!u) {
      user.value = null
    } else {
      user.value = {
        id: u.id,
        email: u.email,
        name: u.full_name,
        role: u.role,
        displayCurrency: u.display_currency,
        company: u.company,
        phone: u.phone,
        // дефолты — на случай, если бэкенд ещё не отдаёт новые поля
        priceDigestEnabled: u.price_digest_enabled ?? false,
        priceDigestSources: u.price_digest_sources ?? [],
        // нет поля в ответе → считаем принятым (не гоняем на /consent без причины)
        consent_accepted: u.consent_accepted ?? true,
      }
    }
    if (cookies) cookies.userC.value = user.value
    persistCookie('auth_user', user.value ? JSON.stringify(user.value) : null, COOKIE_MAX_AGE.user)
  }

  function applyTokens(t: TokenPair) {
    token.value = t.access_token
    if (cookies) {
      cookies.tokenC.value = t.access_token
    }
    persistCookie('auth_token', t.access_token, COOKIE_MAX_AGE.token)
  }

  function clear() {
    user.value = null
    token.value = null
    if (cookies) {
      cookies.tokenC.value = null
      cookies.userC.value = null
    }
    persistCookie('auth_token', null, 0)
    persistCookie('auth_user', null, 0)
  }

  function authHeaders(): Record<string, string> {
    return token.value ? { Authorization: `Bearer ${token.value}` } : {}
  }

  async function login(email: string, password: string) {
    const baseURL = apiBaseURL()
    const pair = await $fetch<TokenPair>('/api/v1/auth/login', {
      baseURL,
      method: 'POST',
      body: { email, password },
      headers: csrfHeaders(),
      credentials: 'include',
    })
    applyTokens(pair)
    await fetchMe()
  }

  async function fetchMe() {
    const baseURL = apiBaseURL()
    const me = await $fetch<UserPublic>('/api/v1/auth/me', {
      baseURL,
      headers: authHeaders(),
      credentials: 'include',
    })
    applyUser(me)
  }

  /** Обновить профиль (PATCH /api/v1/auth/me): валюта, дайджест цен. */
  async function updateMe(patch: UserMePatch): Promise<UserPublic> {
    // useApi берётся лениво (только клиентские submit'ы): при вызове в setup стора
    // получился бы цикл useAuth → useApi → useAuth во время создания стора.
    const { request } = useApi()
    const me = await request<UserPublic>('/api/v1/auth/me', {
      method: 'PATCH',
      body: patch,
    })
    applyUser(me)
    return me
  }

  /** Обновить access-токен. true — успех. */
  async function refresh(): Promise<boolean> {
    const baseURL = apiBaseURL()
    try {
      const pair = await $fetch<TokenPair>('/api/v1/auth/refresh', {
        baseURL,
        method: 'POST',
        headers: csrfHeaders(),
        credentials: 'include',
      })
      applyTokens(pair)
      return true
    } catch {
      return false
    }
  }

  async function logout() {
    const baseURL = apiBaseURL()
    try {
      await $fetch('/api/v1/auth/logout', {
        baseURL,
        method: 'POST',
        headers: { ...authHeaders(), ...csrfHeaders() },
        credentials: 'include',
      })
    } catch {
      // лучшее усилие; профиль чистим локально в любом случае
    }
    clear()
    await navigateTo('/login')
  }

  return {
    user, token,
    isAuthenticated, isClient, isManager,
    registerCookies,
    login, fetchMe, updateMe, refresh, logout, clear, applyUser, applyTokens,
  }
})

// Convenience wrapper (auto-imported by Nuxt)
export function useAuth() {
  return useAuthStore()
}
