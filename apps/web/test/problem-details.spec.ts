import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import type { MappedApiError } from '../types/api'
import {
  getDetailedErrorMessage,
  getErrorMessage,
  getErrorStatus,
  mapProblemDetails,
} from '../utils/errors'

interface MapperCase {
  name: string
  fixture?: string
  input?: unknown
  fallback?: string
  expected: MappedApiError
  detailed?: string
}

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const cases = JSON.parse(
  readFileSync(resolve(webRoot, 'test/fixtures/problem-details-mapper.json'), 'utf8'),
).cases as MapperCase[]

function inputFor(testCase: MapperCase): unknown {
  if (testCase.fixture) {
    return JSON.parse(readFileSync(resolve(webRoot, testCase.fixture), 'utf8'))
  }
  return testCase.input
}

function definedFields(value: MappedApiError): Record<string, unknown> {
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>
}

describe('mapProblemDetails', () => {
  it.each(cases)('$name', (testCase) => {
    const fallback = testCase.fallback ?? 'Не удалось выполнить запрос'
    const input = inputFor(testCase)
    const error = testCase.fixture ? { data: input } : input
    const mapped = mapProblemDetails(error, fallback)

    expect(definedFields(mapped)).toEqual(testCase.expected)
    expect(getErrorStatus(error)).toBe(testCase.expected.status)
    expect(getErrorMessage(error, fallback)).toBe(testCase.expected.message)
    if (testCase.detailed) {
      expect(getDetailedErrorMessage(error, fallback)).toBe(testCase.detailed)
    }
  })
})

describe('getDetailedErrorMessage', () => {
  it('keeps legacy validation details and falls back safely', () => {
    const error = { data: { detail: [{ msg: 'Недостаточно товара' }, { msg: 'Недостаточно товара' }] } }
    expect(getDetailedErrorMessage(error, 'Ошибка')).toBe('Недостаточно товара')
    expect(getDetailedErrorMessage({ data: {} }, 'Ошибка')).toBe('Ошибка')
  })
})

describe('getErrorStatus для ошибок API v2', () => {
  // Регресс, найденный E2E (e2e/catalog.spec.ts): v2-ошибки приходят
  // обёрнутыми в AppProblem, который несёт HTTP-статус в .status и не имеет
  // ни .data, ни .response. Без этой ветки статус терялся, getErrorStatus()
  // отдавал undefined, и проверки `=== 404` на v2-страницах не срабатывали —
  // например, карточка товара показывала «Товар недоступен» вместо
  // «Товар не найден».
  it('берёт статус из AppProblem-подобной ошибки без data/response', () => {
    const appProblem = {
      name: 'AppProblem',
      message: 'Товар не найден',
      status: 404,
      detail: 'Товар не найден',
      isProblemDetails: true,
    }
    expect(getErrorStatus(appProblem)).toBe(404)
    expect(mapProblemDetails(appProblem, 'fallback').status).toBe(404)
  })

  it('не ломает приоритет источников: payload/response важнее error.status', () => {
    expect(getErrorStatus({ data: { status: 422 }, status: 500 })).toBe(422)
    expect(getErrorStatus({ response: { status: 403 }, status: 500 })).toBe(403)
  })

  it('остаётся undefined, когда статуса нигде нет', () => {
    expect(getErrorStatus(new Error('boom'))).toBeUndefined()
    expect(getErrorStatus({})).toBeUndefined()
  })
})
