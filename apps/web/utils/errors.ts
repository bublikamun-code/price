// Безопасный доступ к полям ошибки из catch (e) в strict-режиме (e: unknown).
// FastAPI (HTTPException) кладёт текст в data.detail; ofetch (FetchError) —
// в data / response._data и statusCode / response.status.

/** Минимальная форма ошибки API (ofetch FetchError / FastAPI HTTPException). */
interface ApiErrorLike {
  message?: unknown
  data?: { detail?: unknown; error?: { message?: unknown } }
  response?: { status?: unknown; _data?: { detail?: unknown } }
  statusCode?: unknown
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
