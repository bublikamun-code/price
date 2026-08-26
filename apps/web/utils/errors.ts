// Безопасный доступ к полям ошибки из catch (e) в strict-режиме (e: unknown).
// FastAPI (HTTPException) кладёт текст в data.detail; ofetch (FetchError) —
// в data / response._data и statusCode / response.status.

/** Минимальная форма ошибки API (ofetch FetchError / FastAPI HTTPException). */
interface ApiErrorLike {
  message?: unknown
  data?: { detail?: unknown; error?: { message?: unknown; details?: unknown } }
  response?: { status?: unknown; _data?: { detail?: unknown } }
  statusCode?: unknown
}

/** Рекурсивно собирает человекочитаемые строки из значения ошибки (строки / массивы / объекты). */
function collectLines(v: unknown, out: string[], depth = 0): void {
  if (v == null || depth > 3) return
  if (typeof v === 'string') {
    if (v.trim()) out.push(v.trim())
    return
  }
  if (Array.isArray(v)) {
    v.forEach((item) => collectLines(item, out, depth + 1))
    return
  }
  if (typeof v === 'object') {
    const obj = v as Record<string, unknown>
    // FastAPI 422: [{loc, msg, ...}]; наши детали: {items|details|message|msg}
    const preferred = obj.msg ?? obj.message ?? obj.detail ?? obj.items ?? obj.details
    if (preferred !== undefined) return collectLines(preferred, out, depth + 1)
    for (const key of ['sku', 'error', 'reason']) {
      if (obj[key] != null) collectLines(obj[key], out, depth + 1)
    }
  }
}

/**
 * Человекочитаемые строки из деталей ошибки (422 по остаткам при заказе):
 * FastAPI кладёт список позиций в detail (массив); каждый элемент — строка или {msg/message}.
 * Возвращает соединённый текст либо fallback.
 */
export function getDetailedErrorMessage(e: unknown, fallback: string): string {
  if (!e || typeof e !== 'object') return fallback
  const err = e as ApiErrorLike
  const lines: string[] = []
  collectLines(err.data?.detail, lines)
  if (!lines.length) collectLines(err.response?._data?.detail, lines)
  if (!lines.length) collectLines(err.data?.error?.message ?? err.data?.error?.details, lines)
  const joined = [...new Set(lines)].join('; ')
  return joined || fallback
}

/** Непустая строка → сама, иначе undefined. */
function toText(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined
}

/** HTTP-статус ошибки (response.status / statusCode), если он есть. */
export function getErrorStatus(e: unknown): number | undefined {
  if (!e || typeof e !== 'object') return undefined
  const err = e as ApiErrorLike
  const status = err.response?.status ?? err.statusCode
  return typeof status === 'number' ? status : undefined
}

/**
 * Текст ошибки из unknown. Приоритет: data.detail → response._data.detail → fallback;
 * opts.nested добавляет data.error.message, opts.withMessage — e.message (для Error).
 */
export function getErrorMessage(
  e: unknown,
  fallback: string,
  opts: { nested?: boolean; withMessage?: boolean } = {},
): string {
  if (typeof e === 'string') return toText(e) ?? fallback
  if (!e || typeof e !== 'object') return fallback
  const err = e as ApiErrorLike
  let msg = toText(err.data?.detail)
  if (msg === undefined && opts.nested) msg = toText(err.data?.error?.message)
  if (msg === undefined) msg = toText(err.response?._data?.detail)
  if (msg === undefined && opts.withMessage && e instanceof Error) msg = toText(err.message)
  return msg ?? fallback
}
