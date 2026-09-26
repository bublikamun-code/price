import { beforeEach, describe, expect, it, vi } from 'vitest'

// Nitro-глобалы в обычном vitest не существуют, а middleware их использует
// (defineEventHandler и friends — автоимпорты рантайма). Ставим заглушки и
// подгружаем модуль динамически: проверяем настоящий обработчик, а не копию.
interface FakeEvent {
  headers: Record<string, string>
  protocol: 'http:' | 'https:'
}

type Handler = (event: FakeEvent) => void

async function loadMiddleware(): Promise<Handler> {
  const headers: string[] = []
  vi.stubGlobal('defineEventHandler', (handler: Handler) => handler)
  vi.stubGlobal('setResponseHeader', (event: FakeEvent, name: string, value: string) => {
    event.headers[name] = value
    headers.push(name)
  })
  vi.stubGlobal('getRequestHeader', (event: FakeEvent, name: string) => event.headers[name])
  vi.stubGlobal('getRequestURL', (event: FakeEvent) => ({ protocol: event.protocol }))
  vi.resetModules()
  const mod = await import('../server/middleware/security-headers')
  return (mod.default as unknown as Handler)
}

function makeEvent(overrides: Partial<FakeEvent> = {}): FakeEvent {
  return { headers: {}, protocol: 'http:', ...overrides }
}

describe('security-headers middleware', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('вешает базовый набор заголовков на любой ответ', async () => {
    const handler = await loadMiddleware()
    const event = makeEvent()

    handler(event)

    expect(event.headers['X-Content-Type-Options']).toBe('nosniff')
    expect(event.headers['X-Frame-Options']).toBe('DENY')
    expect(event.headers['Referrer-Policy']).toBe('strict-origin-when-cross-origin')
    expect(event.headers['Permissions-Policy']).toContain('camera=()')
    expect(event.headers['Cross-Origin-Opener-Policy']).toBe('same-origin')
  })

  it('HSTS ставится только на https и по умолчанию равен суткам', async () => {
    const handler = await loadMiddleware()

    const plain = makeEvent()
    handler(plain)
    expect(plain.headers['Strict-Transport-Security']).toBeUndefined()

    const proxied = makeEvent({ headers: { 'x-forwarded-proto': 'https' } })
    handler(proxied)
    expect(proxied.headers['Strict-Transport-Security']).toBe('max-age=86400')

    const direct = makeEvent({ protocol: 'https:' })
    handler(direct)
    expect(direct.headers['Strict-Transport-Security']).toBe('max-age=86400')
  })

  it('берёт первый протокол из цепочки x-forwarded-proto', async () => {
    const handler = await loadMiddleware()
    const event = makeEvent({ headers: { 'x-forwarded-proto': 'https, http' } })

    handler(event)

    expect(event.headers['Strict-Transport-Security']).toBe('max-age=86400')
  })

  it('max-age берётся из HSTS_MAX_AGE в рантайме, без пересборки', async () => {
    vi.stubEnv('HSTS_MAX_AGE', '31536000')
    const handler = await loadMiddleware()
    const event = makeEvent({ protocol: 'https:' })

    handler(event)

    expect(event.headers['Strict-Transport-Security']).toBe('max-age=31536000')
  })

  it('HSTS_MAX_AGE=0 убирает заголовок — аварийный откат политики', async () => {
    vi.stubEnv('HSTS_MAX_AGE', '0')
    const handler = await loadMiddleware()
    const event = makeEvent({ protocol: 'https:' })

    handler(event)

    expect(event.headers['Strict-Transport-Security']).toBeUndefined()
  })

  it('мусор в HSTS_MAX_AGE не ломает заголовок — берётся дефолт', async () => {
    vi.stubEnv('HSTS_MAX_AGE', 'неделя')
    const handler = await loadMiddleware()
    const event = makeEvent({ protocol: 'https:' })

    handler(event)

    expect(event.headers['Strict-Transport-Security']).toBe('max-age=86400')
  })

  it('CSP оставляет домены шрифтов и Метрики: сужение списка убьёт вёрстку', async () => {
    const handler = await loadMiddleware()
    const event = makeEvent()

    handler(event)

    const csp = event.headers['Content-Security-Policy'] ?? ''
    // main.css тянет Manrope/IBM Plex Mono @import'ом с Google Fonts.
    expect(csp).toContain('https://fonts.googleapis.com')
    expect(csp).toContain('https://fonts.gstatic.com')
    // Метрика подключается скриптом tag.js.
    expect(csp).toContain('https://mc.yandex.ru')
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("object-src 'none'")
  })
})

describe('плагин strip-powered-by', () => {
  it('снимает X-Powered-By на хуке beforeResponse', async () => {
    const registered: string[] = []
    const hooks = {
      hook(name: string, cb: (event: unknown) => void) {
        registered.push(name)
        // Заголовок ставит рендерер уже после middleware — проверяем, что
        // именно в этот момент плагин его и убирает.
        const removed: string[] = []
        const event = {
          node: { res: { removeHeader: (h: string) => removed.push(h) } },
        }
        cb(event)
        expect(removed).toContain('X-Powered-By')
      },
    }
    vi.stubGlobal('defineNitroPlugin', (plugin: (app: unknown) => void) => plugin)
    vi.resetModules()
    const mod = await import('../server/plugins/strip-powered-by')
    ;(mod.default as unknown as (app: unknown) => void)({ hooks })

    expect(registered).toEqual(['beforeResponse'])
  })
})
