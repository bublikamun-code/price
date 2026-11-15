// Форма JS-куки `auth_user` и тела запросов аутентификации.
//
// Кука `auth_user` не HttpOnly: её читает любой скрипт страницы. Поэтому в
// ней лежит МИНИМУМ — идентификатор и роль (аудит L10): email, ФИО и компания
// в cookie не попадают. Полный профиль приходит из /api/v1/auth/me и живёт в
// сторе; cookie — только признак «сессия, возможно, есть».
//
// Роль из cookie не является доказательством прав: она не подписана. Гейт роли
// (middleware/role.ts) смотрит на стор, который наполняется ответом /me.
import type { AuthCookiePayload, LoginRequest, TwoFAVerifyRequest, UserRole } from '../types/api'

const USER_ROLES: readonly UserRole[] = ['CLIENT', 'MANAGER', 'ADMIN']

/** Минимальный payload cookie: только id и роль. */
export function cookiePayloadOf(user: { id: string; role: UserRole }): AuthCookiePayload {
  return { id: user.id, role: user.role }
}

/**
 * Разбирает значение куки `auth_user` в минимальный payload.
 *
 * Принимает объект (useCookie уже распарсил JSON) или строку с JSON. Лишние
 * поля — например, email и ФИО из старого формата — отбрасываются: в cookie
 * им не место. Некорректное значение → null (сессии не существует).
 */
export function parseCookiePayload(raw: unknown): AuthCookiePayload | null {
  const record = asRecord(raw)
  if (!record) return null
  const id = typeof record.id === 'string' ? record.id : ''
  const role = record.role
  if (!id || typeof role !== 'string' || !USER_ROLES.includes(role as UserRole)) return null
  return { id, role: role as UserRole }
}

/**
 * True, если в значении куки есть поля сверх id и role.
 *
 * Старая версия клала туда полный профиль (ПДн). Пока такие поля лежат в
 * браузере, cookie переписывается минимальной формой при следующем заходе.
 */
export function cookieHasExtraFields(raw: unknown): boolean {
  const record = asRecord(raw)
  if (!record) return false
  return Object.keys(record).some((key) => key !== 'id' && key !== 'role')
}

/** Тело POST /api/v1/auth/login. remember едет всегда: чекбокс «Запомнить меня». */
export function loginRequestBody(
  email: string,
  password: string,
  remember: boolean,
): LoginRequest {
  return { email, password, remember }
}

/**
 * Тело POST /api/v1/auth/2fa/verify.
 *
 * Бэкенд кладёт claim `remember` в 2FA-ticket и использует его при выдаче
 * cookie; поле в теле — fallback на случай, если claim в ticket нет.
 */
export function twoFAVerifyRequestBody(
  ticket: string,
  code: string,
  remember: boolean,
): TwoFAVerifyRequest {
  return { ticket, code, remember }
}

function asRecord(raw: unknown): Record<string, unknown> | null {
  if (raw && typeof raw === 'object') return raw as Record<string, unknown>
  if (typeof raw === 'string' && raw.trim() !== '') {
    try {
      const parsed: unknown = JSON.parse(raw)
      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
    } catch {
      return null
    }
  }
  return null
}
