import { getErrorMessage, mapProblemDetails } from '../../../utils/errors'
import type { ProblemFieldError } from '../../../types/api'

export interface AppProblemInit {
  code?: string
  title?: string
  detail?: string
  status?: number
  requestId?: string
  fieldErrors?: ProblemFieldError[]
  message: string
  isProblemDetails: boolean
  retryable: boolean
}

export class AppProblem extends Error {
  readonly code?: string
  readonly title?: string
  readonly detail?: string
  readonly status?: number
  readonly requestId?: string
  readonly fieldErrors: ProblemFieldError[]
  readonly isProblemDetails: boolean
  readonly retryable: boolean

  constructor(init: AppProblemInit) {
    super(init.message)
    this.name = 'AppProblem'
    this.code = init.code
    this.title = init.title
    this.detail = init.detail
    this.status = init.status
    this.requestId = init.requestId
    this.fieldErrors = init.fieldErrors ?? []
    this.isProblemDetails = init.isProblemDetails
    this.retryable = init.retryable
  }
}

export function toAppProblem(error: unknown, fallback: string): AppProblem {
  if (error instanceof AppProblem) return error

  const mapped = mapProblemDetails(error, fallback)
  const status = mapped.status
  const retryable =
    status === 429 || (status !== undefined && status >= 500) || status === undefined

  return new AppProblem({
    code: mapped.code,
    title: mapped.title,
    detail: mapped.detail,
    status,
    requestId: mapped.requestId,
    fieldErrors: mapped.errors,
    message: mapped.message,
    isProblemDetails: mapped.isProblemDetails,
    retryable,
  })
}

/**
 * Понятный пользователю текст ошибки: у уже разобранного `AppProblem` берём
 * `detail`/`title` (то, что прислал бэк по RFC 9457), из сырой ошибки v1 —
 * общий маппер. Ничего не выдумываем, fallback — на случай без текста.
 */
export function problemMessage(cause: unknown, fallback: string): string {
  return cause instanceof AppProblem ? cause.message : getErrorMessage(cause, fallback)
}
