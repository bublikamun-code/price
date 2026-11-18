import { describe, expect, it } from 'vitest'

import { apiPath } from '../utils/api-path'

// Префикс публикации подставляется в URL, которые собираются мимо $fetch:
// <img src> фото и EventSource SSE. Обычный стенд — без префикса, публичный
// стенд — '/price' (см. ARCHITECTURE_PLAN.md §16 п.46).
describe('apiPath', () => {
  it('оставляет путь как есть на обычном стенде (префикса нет)', () => {
    expect(apiPath('/api/v1/files/photo?key=abc', '')).toBe('/api/v1/files/photo?key=abc')
  })

  it('добавляет префикс публикации', () => {
    expect(apiPath('/api/v1/files/photo?key=abc', '/price')).toBe(
      '/price/api/v1/files/photo?key=abc',
    )
    expect(apiPath('/api/v1/notifications/stream', '/price')).toBe(
      '/price/api/v1/notifications/stream',
    )
  })

  it('не дублирует слэш на границе префикса и пути', () => {
    expect(apiPath('/api/v1/x', '/price/')).toBe('/price/api/v1/x')
    expect(apiPath('api/v1/x', '/price')).toBe('/price/api/v1/x')
  })

  it('не трогает абсолютный URL другого origin', () => {
    expect(apiPath('/api/v1/x', 'https://cdn.example.com')).toBe('/api/v1/x')
  })
})
