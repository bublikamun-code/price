import { mapProblemDetails } from '../../../utils/errors'
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
