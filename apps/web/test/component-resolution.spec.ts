import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * Vue не падает на неизвестном компоненте: он рендерит пустой кастомный тег.
 * Поэтому опечатка в имени (`ClientCatalogFilters` вместо `CatalogFilters`,
 * `ToastViewport` вместо `UiToastViewport`) молча убирает целый блок UI с
 * прода — без ошибки в консоли, без падения тестов. Этот контракт ловит
 * такие имена на этапе сборки.
 */

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** Nuxt/LiHT-компоненты, доступные в шаблонах без автоимпорта. */
const BUILT_IN = new Set([
  'NuxtPage',
  'NuxtLayout',
  'NuxtLink',
  'NuxtImg',
  'NuxtErrorBoundary',
  'NuxtLoadingIndicator',
  'NuxtWelcome',
  'ClientOnly',
  'RouterLink',
  'RouterView',
  'Transition',
  'TransitionGroup',
  'KeepAlive',
  'Teleport',
  'Suspense',
  // Регистрируется модулем nuxt-icon, а не сканером components/.
  'Icon',
  'component',
  'slot',
  'template',
])

function collectVueFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectVueFiles(full))
    else if (entry.name.endsWith('.vue')) out.push(full)
  }
  return out
}

/**
 * Имена, которые Nuxt регистрирует из components/ при
 * `{ path: '~/components', pathPrefix: false }` (без префикса каталога)
 * и `{ path: '~/components/ui', prefix: 'Ui' }`.
 */
function registeredNames(): Set<string> {
  const componentsDir = resolve(webRoot, 'components')
  const names = new Set<string>()
  for (const file of collectVueFiles(componentsDir)) {
    const base = file.slice(file.lastIndexOf('/') + 1).replace(/\.vue$/, '')
    names.add(base)
    if (file.startsWith(join(componentsDir, 'ui') + '/')) names.add(`Ui${base}`)
  }
  return names
}

/** Только блок <template>: в script-секции `<T>` — это TypeScript-дженерик. */
function templateOf(source: string): string {
  const start = source.indexOf('<template>')
  return start < 0 ? '' : source.slice(start)
}

describe('component name resolution', () => {
  const registered = registeredNames()

  it('registers every component file under a usable name', () => {
    // Guard against a broken helper silently passing everything.
    expect(registered.has('CatalogFilters')).toBe(true)
    expect(registered.has('UiToastViewport')).toBe(true)
  })

  it('resolves every PascalCase component used in a template', () => {
    const unresolved: string[] = []
    const files = [
      join(webRoot, 'app.vue'),
      ...collectVueFiles(resolve(webRoot, 'components')),
      ...collectVueFiles(resolve(webRoot, 'pages')),
      ...collectVueFiles(resolve(webRoot, 'layouts')),
    ]

    for (const file of files) {
      const template = templateOf(readFileSync(file, 'utf8'))
      for (const match of template.matchAll(/<([A-Z][A-Za-z0-9]*)(\s[^>]*?)?\/?>/g)) {
        const name = match[1]
        const attrs = match[2] ?? ''
        // `<Foo(...)` или `<Foo<T>` — это вызов/дженерик в выражении, а не тег.
        if (attrs.startsWith('(') || attrs.startsWith('<')) continue
        if (BUILT_IN.has(name) || registered.has(name)) continue
        unresolved.push(`${name} → ${file.slice(webRoot.length + 1)}`)
      }
    }

    expect([...new Set(unresolved)]).toEqual([])
  })

  it('keeps the catalog filters mounted and toasts reachable', () => {
    const catalog = readFileSync(resolve(webRoot, 'pages/catalog/index.vue'), 'utf8')
    const app = readFileSync(resolve(webRoot, 'app.vue'), 'utf8')
    // Регрессии, которые уже уезжали на прод как пустые блоки.
    expect(catalog).not.toContain('<ClientCatalogFilters')
    expect(catalog.match(/<CatalogFilters/g) ?? []).toHaveLength(2)
    expect(app).toContain('<UiToastViewport')
    expect(app).not.toContain('<ToastViewport')
  })
})
