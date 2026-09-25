import type { FetchOptions } from 'ofetch'
import type { z } from 'zod'
import { toAppProblem } from './problem'

export type ApiRequester = <T>(url: string, options?: FetchOptions) => Promise<T>

export type ApiRequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export type ApiRequestOptions = Omit<FetchOptions, 'method'> & {
  method: ApiRequestMethod
}

export interface ApiResponse<T> {
  data: T
  etag: string | null
  idempotencyReplayed: boolean
}

export interface ApiContractErrorInit {
  path: string
  issues: z.ZodIssue[]
}

export class ApiContractError extends Error {
  readonly path: string
  readonly issues: z.ZodIssue[]

  constructor(init: ApiContractErrorInit) {
    super(`Invalid API v2 response for ${init.path}`)
    this.name = 'ApiContractError'
    this.path = init.path
    this.issues = init.issues
  }
}

export interface ApiV2Client {
  get<T>(path: string, schema: z.ZodType<T>): Promise<T>
  execute<T>(path: string, schema: z.ZodType<T>, options: ApiRequestOptions): Promise<ApiResponse<T>>
}

export function createApiV2Client(request: ApiRequester): ApiV2Client {
  async function execute<T>(
    path: string,
    schema: z.ZodType<T>,
    options: ApiRequestOptions,
  ): Promise<ApiResponse<T>> {
    let etag: string | null = null
    let idempotencyReplayed = false
    const captureResponse = ({ response }: { response: Response }) => {
      etag = response.headers.get('etag')
      idempotencyReplayed = response.headers.get('x-idempotency-replayed') === 'true'
    }
    const existingHooks = options.onResponse
    const onResponse = existingHooks
      ? Array.isArray(existingHooks)
        ? [...existingHooks, captureResponse]
        : [existingHooks, captureResponse]
      : [captureResponse]

    let raw: unknown
    try {
      raw = await request<unknown>(path, { ...options, onResponse })
    } catch (error) {
      throw toAppProblem(error, 'Не удалось выполнить запрос')
    }

    const parsed = schema.safeParse(raw)
    if (!parsed.success) {
      throw new ApiContractError({ path, issues: parsed.error.issues })
    }
    return { data: parsed.data, etag, idempotencyReplayed }
  }

  return {
    get<T>(path: string, schema: z.ZodType<T>) {
      return execute(path, schema, { method: 'GET' }).then((response) => response.data)
    },
    execute,
  }
}
