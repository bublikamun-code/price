import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Контракт иконок. Раньше <Icon> ходил за наборами в api.iconify.design, а
// прод-CSP (infra/nginx/nginx.prod.conf) режет connect-src до 'self' — вместо
// глифа на экран попадало само имя иконки. Теперь наборы ставятся локально и
// попадают в бандл на сборке, а этот тест не даёт протащить имя, которого в
// наборе нет: такие имена молча рисуются текстом при любом раскладе.

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (path: string) => readFileSync(resolve(webRoot, path), 'utf8')

const pkg = JSON.parse(read('package.json')) as {
  dependencies?: Record<string, string>
}
const installedCollections = ['heroicons', 'simple-icons']
const SCAN_DIRS = ['components', 'composables', 'layouts', 'pages', 'plugins', 'app.vue']
const SKIP_DIRS = new Set(['node_modules', '.nuxt', '.output', '.git', 'test', 'tests'])

function collectSourceFiles(target: string): string[] {
  const absolute = resolve(webRoot, target)
  if (!statSync(absolute).isDirectory()) return [absolute]
  const files: string[] = []
  for (const entry of readdirSync(absolute, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue
    const child = join(absolute, entry.name)
    if (entry.isDirectory()) files.push(...collectSourceFiles(relative(webRoot, child)))
    else if (/\.(vue|ts)$/.test(entry.name)) files.push(child)
  }
  return files
}

const sourceFiles = SCAN_DIRS.flatMap((dir) => collectSourceFiles(dir))
const usedIcons = new Map<string, Set<string>>()
for (const file of sourceFiles) {
  const code = readFileSync(file, 'utf8')
  for (const match of code.matchAll(/["'`]([a-z0-9-]+):([a-z0-9-]+)["'`]/g)) {
    const [, collection, name] = match
    if (!installedCollections.includes(collection)) continue
    if (!usedIcons.has(name)) usedIcons.set(name, new Set())
    usedIcons.get(name)!.add(relative(webRoot, file))
  }
}

function collectionIcons(collection: string): Record<string, unknown> {
  const file = resolve(webRoot, 'node_modules', `@iconify-json/${collection}/icons.json`)
  const data = JSON.parse(readFileSync(file, 'utf8')) as { icons: Record<string, unknown> }
  return data.icons
}

describe('icon set contract', () => {
  it('ships the used collections as dependencies instead of fetching them at runtime', () => {
    for (const collection of installedCollections) {
      expect(pkg.dependencies).toHaveProperty(`@iconify-json/${collection}`)
    }
    // Модуль переехал с nuxt-icon на @nuxt/icon: только он умеет собрать
    // нужные иконки на сборке из локальных наборов.
    expect(pkg.dependencies).toHaveProperty('@nuxt/icon')
    expect(pkg.dependencies).not.toHaveProperty('nuxt-icon')

    const config = read('nuxt.config.ts')
    expect(config).toContain("'@nuxt/icon'")
    expect(config).toContain("serverBundle: 'local'")
    // scan нужен, чтобы в клиентский бандл попали иконки, названные не в
    // шаблоне, а в данных (массивы меню, composables) — иначе они ушли бы в
    // api.iconify.design, и на проде вернулись бы иконки-имена.
    expect(config).toContain('scan:')
    expect(config).toContain('globInclude:')
    expect(config).toContain('.{vue,ts,tsx,js,jsx,md,mdc,mdx}')
  })

  it('uses icon names that exist in the installed sets', () => {
    const known = new Set([
      ...Object.keys(collectionIcons('heroicons')),
      ...Object.keys(collectionIcons('simple-icons')),
    ])
    const missing = [...usedIcons.entries()]
      .filter(([name]) => !known.has(name))
      .map(([name, files]) => `${name} (${[...files].join(', ')})`)
      .sort()

    expect(missing).toEqual([])
  })

  it('finds the icon names it is meant to guard', () => {
    // Пустой скан прошёл бы на любом сломанном glob — фиксируем нижнюю границу.
    expect(usedIcons.size).toBeGreaterThan(50)
  })
})
