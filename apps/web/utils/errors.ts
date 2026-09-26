// Безопасный доступ к полям ошибки из catch (e) в strict-режиме (e: unknown).
// v1 FastAPI ошибки и v2 RFC 9457 Problem Details нормализуются в одном mapper.

import type { MappedApiError, ProblemFieldError } from '../types/api'

type ErrorRecord = Record<string, unknown>

interface ApiErrorLike {
  message?: unknown
  data?: unknown
  response?: { status?: unknown; _data?: unknown }
  statusCode?: unknown
}

function asRecord(value: unknown): ErrorRecord | undefined {
  return value !== null && typeof value === 'object' ? (value as ErrorRecord) : undefined
}

function toText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function toStatus(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) ? value : undefined
}

function responsePayload(e: unknown): ErrorRecord | undefined {
  if (!e || typeof e !== 'object') return undefined
  const err = e as ApiErrorLike
  return asRecord(err.data) ?? asRecord(err.response?._data)
}

function errorResponse(e: unknown): ErrorRecord | undefined {
  if (!e || typeof e !== 'object') return undefined
  const err = e as ApiErrorLike
  return asRecord(err.response)
}

function problemErrors(payload: ErrorRecord | undefined): ProblemFieldError[] {
  if (!payload || !Array.isArray(payload.errors)) return []
  return payload.errors.flatMap((item) => {
    const value = asRecord(item)
    const field = toText(value?.field)
    const code = toText(value?.code)
    const message = toText(value?.message)
    return field && code && message ? [{ field, code, message }] : []
  })
}

/** Maps a v2 Problem Details payload or a legacy API error to one stable shape. */
export function mapProblemDetails(e: unknown, fallback: string): MappedApiError {
  const payload = responsePayload(e)
  const response = errorResponse(e)
  const nested = asRecord(payload?.error)
  const status =
    toStatus(payload?.status) ??
    toStatus(response?.status) ??
    (e && typeof e === 'object' ? toStatus((e as ApiErrorLike).statusCode) : undefined)
  const errors = problemErrors(payload)
  const detail = toText(payload?.detail)
  const title = toText(payload?.title)
  const code = toText(payload?.code)
  const isProblemDetails = Boolean(
    code && (detail || title) && toStatus(payload?.status) !== undefined,
  )

  return {
    status,
    type: toText(payload?.type),
    title,
    detail,
    instance: toText(payload?.instance),
    code,
    requestId: toText(payload?.requestId),
    errors,
    message: detail ?? toText(nested?.message) ?? toText(nested?.details) ?? title ?? fallback,
    isProblemDetails,
  }
}

/** Recursively collects human-readable strings from legacy validation details. */
function collectLines(v: unknown, out: string[], depth = 0): void {
  if (v == null || depth > 3) return
  if (typeof v === 'string') {
    const text = toText(v)
    if (text) out.push(text)
    return
  }
  if (Array.isArray(v)) {
    v.forEach((item) => collectLines(item, out, depth + 1))
    return
  }
  if (typeof v === 'object') {
    const obj = v as ErrorRecord
    const preferred = obj.msg ?? obj.message ?? obj.detail ?? obj.items ?? obj.details
    if (preferred !== undefined) return collectLines(preferred, out, depth + 1)
    for (const key of ['sku', 'error', 'reason']) {
      if (obj[key] != null) collectLines(obj[key], out, depth + 1)
    }
  }
}

/**
 * Человекочитаемые строки из деталей ошибки (422 по остаткам при заказе).
 * Для v2 field errors сохраняет поле, чтобы UI мог показать точный адрес ошибки.
 */
export function getDetailedErrorMessage(e: unknown, fallback: string): string {
  const mapped = mapProblemDetails(e, fallback)
  if (mapped.errors.length) {
    return [...new Set(mapped.errors.map((item) => `${item.field}: ${item.message}`))].join('; ')
  }

  const lines: string[] = []
  const payload = responsePayload(e)
  collectLines(payload?.detail, lines)
  if (!lines.length) collectLines(asRecord(payload?.error)?.message, lines)
  if (!lines.length) collectLines(asRecord(payload?.error)?.details, lines)
  const joined = [...new Set(lines)].join('; ')
  return joined || mapped.message || fallback
}

/** HTTP-статус ошибки, включая RFC 9457 status. */
export function getErrorStatus(e: unknown): number | undefined {
  return mapProblemDetails(e, '').status
}

/**
 * Отказ именно в сессии (401/403), а не сбой связи с API.
 *
 * Различие принципиально для подтверждения сессии при SSR и гидрации: стирать
 * cookie по любой ошибке нельзя, иначе недоступный API или 5xx выкидывали бы
 * живых пользователей из сессии навсегда. Сброс делаем только когда сервер
 * прямо сказал «доступа нет»; всё остальное — «не удалось спросить».
 */
export function isSessionRejected(e: unknown): boolean {
  const status = getErrorStatus(e)
  return status === 401 || status === 403
}

/**
 * Текст ошибки из unknown. Приоритет: v2 detail/title → legacy detail/error →
 * Error.message (при opts.withMessage) → fallback.
 */
export function getErrorMessage(
  e: unknown,
  fallback: string,
  opts: { nested?: boolean; withMessage?: boolean } = {},
): string {
  if (typeof e === 'string') return toText(e) ?? fallback
  if (!e || typeof e !== 'object') return fallback

  const mapped = mapProblemDetails(e, fallback)
  if (mapped.message !== fallback) return mapped.message
  if (opts.nested) {
    const payload = responsePayload(e)
    const nested = asRecord(payload?.error)
    const message = toText(nested?.message) ?? toText(nested?.details)
    if (message) return message
  }
  if (opts.withMessage && e instanceof Error) return toText(e.message) ?? fallback
  return fallback
}
