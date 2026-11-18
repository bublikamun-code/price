import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
  cookieHasExtraFields,
  cookiePayloadOf,
  loginRequestBody,
  parseCookiePayload,
  twoFAVerifyRequestBody,
} from '../utils/auth-cookie'

// Аудит L10: JS-кука `auth_user` доступна любому скрипту страницы, поэтому в
// ней лежит минимум — id и роль. Email/ФИО/компания в cookie не попадают.
// Аудит L9: чекбокс «Запомнить меня» едет в теле login и 2fa/verify.
//
// Часть проверок — по исходникам: composable и плагин завязаны на Nuxt-контекст
// (useCookie, Pinia, runtime), поднять их в vitest без окружения нельзя,
// поэтому стражим именно форму запросов и форму cookie.

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (relativePath: string) => readFileSync(resolve(webRoot, relativePath), 'utf8')

const useAuthSource = read('composables/useAuth.ts')
const sessionPluginSource = read('plugins/auth.session.ts')
const loginPageSource = read('pages/login.vue')

describe('cookie auth_user: только id и роль (L10)', () => {
  it('cookiePayloadOf оставляет ровно два поля', () => {
    const payload = cookiePayloadOf({ id: 'u-1', role: 'CLIENT' })

    expect(payload).toEqual({ id: 'u-1', role: 'CLIENT' })
    expect(Object.keys(payload).sort()).toEqual(['id', 'role'])
  })

  it('cookiePayloadOf не тащит ПДн из полного профиля', () => {
    const payload = cookiePayloadOf({
      id: 'u-1',
      role: 'MANAGER',
      email: 'manager@example.com',
      name: 'Иван Иванов',
      company: 'ООО Ромашка',
      phone: '+70000000000',
    } as never)

    expect(payload).toEqual({ id: 'u-1', role: 'MANAGER' })
    expect(JSON.stringify(payload)).not.toContain('example.com')
    expect(JSON.stringify(payload)).not.toContain('Ромашка')
  })

  it('parseCookiePayload отбрасывает лишние поля старого формата', () => {
    const parsed = parseCookiePayload({
      id: 'u-1',
      role: 'ADMIN',
      email: 'admin@example.com',
      name: 'Админ',
      company: 'ООО Ромашка',
    })

    expect(parsed).toEqual({ id: 'u-1', role: 'ADMIN' })
    expect(Object.keys(parsed!).sort()).toEqual(['id', 'role'])
  })

  it('parseCookiePayload принимает JSON-строку (как в document.cookie)', () => {
    expect(parseCookiePayload('{"id":"u-2","role":"CLIENT"}')).toEqual({
      id: 'u-2',
      role: 'CLIENT',
    })
  })

  it('parseCookiePayload отсекает мусор и неизвестные роли', () => {
    expect(parseCookiePayload(null)).toBeNull()
    expect(parseCookiePayload('')).toBeNull()
    expect(parseCookiePayload('не json')).toBeNull()
    expect(parseCookiePayload({ role: 'CLIENT' })).toBeNull()
    expect(parseCookiePayload({ id: 'u-1', role: 'ROOT' })).toBeNull()
  })

  it('cookieHasExtraFields ловит старый формат с ПДн', () => {
    expect(cookieHasExtraFields({ id: 'u-1', role: 'CLIENT' })).toBe(false)
    expect(cookieHasExtraFields({ id: 'u-1', role: 'CLIENT', email: 'a@b.c' })).toBe(true)
    expect(cookieHasExtraFields({ email: 'a@b.c' })).toBe(true)
    expect(cookieHasExtraFields(null)).toBe(false)
  })
})

describe('запросы входа: remember едет в теле (L9)', () => {
  it('loginRequestBody всегда содержит remember', () => {
    expect(loginRequestBody('a@b.c', 'secret', true)).toEqual({
      email: 'a@b.c',
      password: 'secret',
      remember: true,
    })
    expect(loginRequestBody('a@b.c', 'secret', false).remember).toBe(false)
  })

  it('twoFAVerifyRequestBody содержит remember как fallback', () => {
    expect(twoFAVerifyRequestBody('ticket-1', '123456', true)).toEqual({
      ticket: 'ticket-1',
      code: '123456',
      remember: true,
    })
    expect(twoFAVerifyRequestBody('ticket-1', '123456', false).remember).toBe(false)
  })

  it('стор отправляет remember в login и в 2fa/verify', () => {
    expect(useAuthSource).toContain('body: loginRequestBody(email, password, remember)')
    expect(useAuthSource).toContain('body: twoFAVerifyRequestBody(ticket, code, remember)')
    expect(useAuthSource).toMatch(/async function login\(email: string, password: string, remember = true\)/)
    expect(useAuthSource).toMatch(/async function verify2fa\(ticket: string, code: string, remember = true\)/)
  })

  it('страница входа передаёт значение чекбокса в оба шага', () => {
    expect(loginPageSource).toContain('auth.login(email.value, password.value, remember.value)')
    expect(loginPageSource).toContain('auth.verify2fa(ticket.value, code.value.trim(), remember.value)')
    expect(loginPageSource).toContain('v-model="remember"')
  })
})

describe('cookie auth_user пишется и читается в минимальной форме (L10)', () => {
  it('applyUser кладёт в cookie только id и роль, профиль остаётся в сторе', () => {
    expect(useAuthSource).toContain('const cookiePayload = user.value ? cookiePayloadOf(user.value) : null')
    expect(useAuthSource).toContain(
      "persistCookie('auth_user', cookiePayload ? JSON.stringify(cookiePayload) : null, COOKIE_MAX_AGE.user)",
    )
    // Полный профиль в cookie не пишется — ни напрямую, ни через JSON.stringify.
    expect(useAuthSource).not.toContain('JSON.stringify(user.value)')
  })

  it('плагин не доверяет cookie на сервере: профиль берётся только из /me', () => {
    expect(sessionPluginSource).toContain('auth.user = null')
    expect(sessionPluginSource).toContain('useCookie<AuthCookiePayload | null>(\'auth_user\'')
    // Из cookie в auth.user профиль не подставляется.
    expect(sessionPluginSource).not.toMatch(/auth\.user\s*=\s*cookieIdentity/)
    expect(sessionPluginSource).not.toMatch(/auth\.user\s*=\s*userC\.value/)
  })

  it('старый формат cookie с ПДн переписывается минимальной формой', () => {
    expect(sessionPluginSource).toContain('cookieHasExtraFields(userC.value)')
    expect(sessionPluginSource).toContain('auth.persistCookieIdentity(cookieIdentity)')
    expect(useAuthSource).toContain('function persistCookieIdentity(payload: AuthCookiePayload)')
  })
})
