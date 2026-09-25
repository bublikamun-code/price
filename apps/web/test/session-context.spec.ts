import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import {
  ApiContractError,
  createApiV2Client,
  type ApiRequester,
} from '../domain/api/v2/client'
import { AppProblem, toAppProblem } from '../domain/api/v2/problem'
import { sessionResponseSchema } from '../domain/api/v2/session.schema'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const apiFixture = (name: string) =>
  readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8')

function requestReturning(value: unknown): ApiRequester {
  return async <T>(_url: string, _options?: FetchOptions) => value as T
}

function requestFailing(error: unknown): ApiRequester {
  return async <T>(_url: string, _options?: FetchOptions): Promise<T> => {
    throw error
  }
}

describe('API v2 session contract', () => {
  it('validates the shared session fixture and preserves metadata', async () => {
    const fixture = JSON.parse(apiFixture('session_success.json'))
    const client = createApiV2Client(requestReturning(fixture))

    const response = await client.get('/api/v2/session', sessionResponseSchema)

    expect(response.data.commercialScope).toBe('USER')
    expect(response.data.organizationId).toBeNull()
    expect(response.data.memberships).toEqual([])
    expect(response.data.user.legacyCompany).toBe('СтройТрейд')
    expect(response.meta.requestId).toBe('v2-fixture-session-001')
  })

  it('rejects a malformed successful response as a contract error', async () => {
    const client = createApiV2Client(
      requestReturning({ data: { commercialScope: 'USER' }, meta: { requestId: 'x' } }),
    )

    await expect(client.get('/api/v2/session', sessionResponseSchema)).rejects.toBeInstanceOf(
      ApiContractError,
    )
  })

  it('normalizes Problem Details into AppProblem', async () => {
    const fixture = JSON.parse(apiFixture('problem_validation_error.json'))
    const client = createApiV2Client(requestFailing({ data: fixture }))

    const error = await client
      .get('/api/v2/session', sessionResponseSchema)
      .then(() => null)
      .catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(AppProblem)
    expect(error).toMatchObject({
      code: 'VALIDATION_ERROR',
      status: 422,
      requestId: 'v2-fixture-validation-001',
      retryable: false,
    })
    expect((error as AppProblem).fieldErrors).toHaveLength(1)
  })

  it('marks network failures as retryable without dropping the original cause', () => {
    const problem = toAppProblem(new Error('network unavailable'), 'Ошибка сети')

    expect(problem.retryable).toBe(true)
    expect(problem.status).toBeUndefined()
    expect(problem.isProblemDetails).toBe(false)
  })
})
