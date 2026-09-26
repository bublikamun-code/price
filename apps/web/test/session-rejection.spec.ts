import { describe, expect, it } from 'vitest'

import { getErrorStatus, isSessionRejected } from '../utils/errors'

/**
 * Различение «сессию отбили» и «не получилось спросить» решает, стирать ли
 * cookie. Ошиблись мы в одну сторону — пользователей выкинет из сессии при
 * первом же 5xx, в другую — поддельная/протухшая сессия будет считаться живой.
 */
describe('isSessionRejected', () => {
  it('признаёт отказ по кодам 401 и 403 в разных форматах ошибки', () => {
    // ofetch кладёт код в statusCode...
    expect(isSessionRejected(Object.assign(new Error('Unauthorized'), { statusCode: 401 }))).toBe(true)
    // ...и дублирует в response.status
    expect(isSessionRejected({ response: { status: 401 } })).toBe(true)
    // v2 Problem Details: код лежит в теле ответа
    expect(isSessionRejected({ data: { status: 403, code: 'FORBIDDEN', title: 'Forbidden' } })).toBe(true)
  })

  it('не считает отказом ошибки сервера и прокси: сессию стирать нельзя', () => {
    expect(isSessionRejected(Object.assign(new Error('Internal'), { statusCode: 500 }))).toBe(false)
    expect(isSessionRejected({ response: { status: 502 } })).toBe(false)
    expect(isSessionRejected({ response: { status: 504 } })).toBe(false)
  })

  it('не считает отказом сетевые сбои без кода ответа', () => {
    expect(isSessionRejected(new Error('fetch failed'))).toBe(false)
    expect(isSessionRejected('timeout')).toBe(false)
    expect(isSessionRejected(undefined)).toBe(false)
    expect(isSessionRejected(null)).toBe(false)
  })

  it('404 — это не отказ в доступе: неверный адрес не должен разлогинивать', () => {
    expect(isSessionRejected({ response: { status: 404 } })).toBe(false)
  })

  it('getErrorStatus по-прежнему отдаёт код — хелпер на нём и построен', () => {
    expect(getErrorStatus({ data: { status: 401 } })).toBe(401)
    expect(getErrorStatus(new Error('boom'))).toBeUndefined()
  })
})
