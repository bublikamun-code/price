import { beforeEach, describe, expect, it, vi } from 'vitest'

// Nitro-глобалы в обычном vitest не существуют, а middleware их использует
// (defineEventHandler и friends — автоимпорты рантайма). Ставим заглушки и
// подгружаем модуль динамически: проверяем настоящий обработчик, а не копию.
interface FakeEvent {
  headers: Record<string, string>
  protocol: 'http:' | 'https:'
  // prod-ветка кладёт сюда nonce, хук render:html его оттуда читает.
  context: Record<string, unknown>
}

type Handler = (event: FakeEvent) => void
type RenderHook = (html: unknown, ctx: { event: FakeEvent }) => void

async function loadMiddleware(): Promise<Handler> {
  vi.stubGlobal('defineEventHandler', (handler: Handler) => handler)
  vi.stubGlobal('setResponseHeader', (event: FakeEvent, name: string, value: string) => {
    event.headers[name] = value
  })
  vi.stubGlobal('getRequestHeader', (event: FakeEvent, name: string) => event.headers[name])
  vi.stubGlobal('getRequestURL', (event: FakeEvent) => ({ protocol: event.protocol }))
  vi.resetModules()
  const mod = await import('../server/middleware/security-headers')
  return (mod.default as unknown as Handler)
}

async function loadInjectScriptNonce(): Promise<(html: string, nonce: string) => string> {
  vi.stubGlobal('defineEventHandler', (handler: unknown) => handler)
  vi.resetModules()
  const mod = await import('../server/middleware/security-headers')
  return mod.injectScriptNonce as (html: string, nonce: string) => string
}

/**
 * Prod-загрузка: NODE_ENV=production + заглушка nitroApp. render:html-хук
 * middleware регистрирует через useNitroApp().hooks.hook — ловим его сюда.
 * Возвращаем сам реестр, а не hooks['render:html']: хук появляется только
 * после первого вызова handler (ленивая регистрация).
 */
async function loadProdMiddleware(): Promise<{
  handler: Handler
  hooks: Record<string, RenderHook>
}> {
  const hooks: Record<string, RenderHook> = {}
  vi.stubEnv('NODE_ENV', 'production')
  vi.stubGlobal('useNitroApp', () => ({
    hooks: {
      hook(name: string, cb: RenderHook) {
        hooks[name] = cb
      },
    },
  }))
  const handler = await loadMiddleware()
  return { handler, hooks }
}

function makeEvent(overrides: Partial<FakeEvent> = {}): FakeEvent {
  return { headers: {}, protocol: 'http:', context: {}, ...overrides }
}

function scriptSrcDirective(csp: string): string {
  const directive = csp.split('; ').find((d) => d.startsWith('script-src'))
  expect(directive, 'script-src отсутствует в CSP').toBeDefined()
  return directive!
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

  it('HSTS по умолчанию не ставится — владелец заголовка edge-nginx (DEC-01)', async () => {
    const handler = await loadMiddleware()

    const plain = makeEvent()
    handler(plain)
    expect(plain.headers['Strict-Transport-Security']).toBeUndefined()

    const proxied = makeEvent({ headers: { 'x-forwarded-proto': 'https' } })
    handler(proxied)
    expect(proxied.headers['Strict-Transport-Security']).toBeUndefined()

    const direct = makeEvent({ protocol: 'https:' })
    handler(direct)
    expect(direct.headers['Strict-Transport-Security']).toBeUndefined()
  })

  it('с заданным HSTS_MAX_AGE заголовок ставится только на https', async () => {
    vi.stubEnv('HSTS_MAX_AGE', '86400')
    const handler = await loadMiddleware()

    const plain = makeEvent()
    handler(plain)
    expect(plain.headers['Strict-Transport-Security']).toBeUndefined()

    const direct = makeEvent({ protocol: 'https:' })
    handler(direct)
    expect(direct.headers['Strict-Transport-Security']).toBe('max-age=86400')
  })

  it('берёт первый протокол из цепочки x-forwarded-proto', async () => {
    vi.stubEnv('HSTS_MAX_AGE', '86400')
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

  it('мусор в HSTS_MAX_AGE не включает заголовок — fail-closed', async () => {
    vi.stubEnv('HSTS_MAX_AGE', 'неделя')
    const handler = await loadMiddleware()
    const event = makeEvent({ protocol: 'https:' })

    handler(event)

    expect(event.headers['Strict-Transport-Security']).toBeUndefined()
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

describe('CSP в dev — прежняя статическая политика', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('script-src с unsafe-inline, без nonce; nonce в context не кладётся', async () => {
    // NODE_ENV не стабаем (vitest даёт 'test') — middleware уходит в dev-ветку.
    // useNitroApp не стабаем намеренно: если dev-ветка его тронет, тест упадёт
    // по ReferenceError — это и есть фиксация «хук в dev не регистрируется».
    const handler = await loadMiddleware()
    const event = makeEvent()

    handler(event)

    const csp = event.headers['Content-Security-Policy'] ?? ''
    expect(scriptSrcDirective(csp)).toContain("'unsafe-inline'")
    expect(csp).not.toContain('nonce-')
    expect(event.context.__cspNonce).toBeUndefined()
  })
})

describe('CSP в prod — nonce без unsafe-inline (DEC-02)', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('enforcing CSP: script-src с nonce и без unsafe-inline, style-src не тронут', async () => {
    const { handler } = await loadProdMiddleware()
    const event = makeEvent()

    handler(event)

    // Enforcing, а не Report-Only: Report-Only ничего не блокирует.
    expect(event.headers['Content-Security-Policy']).toBeDefined()
    expect(event.headers['Content-Security-Policy-Report-Only']).toBeUndefined()

    const csp = event.headers['Content-Security-Policy']!
    const scriptSrc = scriptSrcDirective(csp)
    expect(scriptSrc).toContain("'self'")
    expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/=]+'/)
    expect(scriptSrc).toContain('https://mc.yandex.ru')
    // Внешний скрипт Telegram Web App (layouts/miniapp.vue).
    expect(scriptSrc).toContain('https://telegram.org')
    expect(scriptSrc).not.toContain('unsafe-inline')
    // Динамические :style-биндинги компонентов — unsafe-inline в style-src
    // остаётся осознанно (§16 п.30(2)).
    expect(csp.split('; ').find((d) => d.startsWith('style-src'))).toContain("'unsafe-inline'")
  })

  it('nonce из context совпадает с заголовком и проставляется хуком в инлайн-скрипты', async () => {
    const { handler, hooks } = await loadProdMiddleware()
    const event = makeEvent()

    handler(event)
    const renderHook = hooks['render:html']
    expect(renderHook).toBeDefined()

    const nonce = event.context.__cspNonce
    expect(typeof nonce).toBe('string')
    expect(event.headers['Content-Security-Policy']).toContain(`'nonce-${nonce}'`)

    // Рантайм рендера отдаёт поля и массивами, и строками — хук обязан уметь оба.
    const html = {
      head: ['<script>"payload"</script><script src="/_nuxt/entry.js"></script>'],
      body: '<script>window.__APP__=1</script>',
      bodyPrepend: ['<script type="application/json">{"a":1}</script>'],
      bodyAppend: [],
    }
    renderHook(html, { event })

    expect(html.head[0]).toBe(
      `<script nonce="${nonce}">"payload"</script><script src="/_nuxt/entry.js"></script>`,
    )
    expect(html.body).toBe(`<script nonce="${nonce}">window.__APP__=1</script>`)
    expect(html.bodyPrepend[0]).toBe(`<script nonce="${nonce}" type="application/json">{"a":1}</script>`)
    expect(html.bodyAppend).toEqual([])
  })

  it('nonce уникален между двумя запросами', async () => {
    const { handler } = await loadProdMiddleware()

    const first = makeEvent()
    const second = makeEvent()
    handler(first)
    handler(second)

    const n1 = first.context.__cspNonce
    const n2 = second.context.__cspNonce
    expect(typeof n1).toBe('string')
    expect(n1).not.toBe(n2)
    expect(first.headers['Content-Security-Policy']).not.toBe(second.headers['Content-Security-Policy'])
  })

  it('хук render:html регистрируется один раз за жизнь модуля, инъекция идемпотентна', async () => {
    const registered: string[] = []
    const hooksHolder: { renderHook?: RenderHook } = {}
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubGlobal('useNitroApp', () => ({
      hooks: {
        hook(name: string, cb: RenderHook) {
          registered.push(name)
          hooksHolder.renderHook = cb
        },
      },
    }))
    const handler = await loadMiddleware()

    const first = makeEvent()
    const second = makeEvent()
    handler(first)
    handler(second)

    expect(registered.filter((n) => n === 'render:html')).toHaveLength(1)

    const nonce = second.context.__cspNonce as string
    const html = { head: ['<script>a</script>'] }
    hooksHolder.renderHook!(html, { event: second })
    hooksHolder.renderHook!(html, { event: second })
    expect(html.head[0]).toBe(`<script nonce="${nonce}">a</script>`)
  })
})

describe('injectScriptNonce (чистая функция)', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('проставляет nonce всем инлайн-скриптам, src-теги не трогает', async () => {
    const inject = await loadInjectScriptNonce()

    const html =
      '<html><head><script>"x"</script><script src="a.js" defer></script></head>' +
      '<body><SCRIPT>var y=1</SCRIPT><script type="application/json">{}</script>' +
      '<img data-src="p.png"></body></html>'
    const out = inject(html, 'AB12+/==')

    expect(out).toContain('<script nonce="AB12+/==">"x"</script>')
    // Регистр тега сохраняется, атрибут добавляется перед прочими.
    expect(out).toContain('<SCRIPT nonce="AB12+/==">var y=1</SCRIPT>')
    expect(out).toContain('<script nonce="AB12+/==" type="application/json">{}</script>')
    expect(out).toContain('<script src="a.js" defer></script>')
    // data-src не должен всплывать как src (проверка (^|\s) в регэкспе).
    expect(out).toContain('<img data-src="p.png">')
  })

  it('идемпотентен: второй прогон не дублирует nonce', async () => {
    const inject = await loadInjectScriptNonce()

    const once = inject('<script>a</script><script src="b.js"></script>', 'NN==')
    const twice = inject(once, 'NN==')

    expect(twice).toBe(once)
    expect((once.match(/nonce=/g) ?? []).length).toBe(1)
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
