import { describe, expect, it } from 'vitest'

/**
 * Индикатор обрыва связи.
 *
 * Каталог интерактивен целиком (корзина, заявка, загрузка прайса), и без индикации
 * пользователь при обрыве просто нажимает кнопку и не получает ответа.
 *
 * Тут проверяется контракт компонента на уровне исходника: сам композабл
 * `useOnline` работает на `window`, поэтому проверять его поведение имеет смысл
 * только вместе с DOM-окружением. Зато очень легко случайно (а) убрать баннер из
 * layout'а или (б) начать показывать его сразу при загрузке страницы без сети —
 * во втором случае баннер встречает пользователя на входе и мешает понять, что
 * приложение надо обновить.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), 'utf8')

describe('баннер офлайна', () => {
  it('подключён во всех layout’ах, где пользователь что-то делает', () => {
    for (const layout of ['default', 'client', 'manager', 'auth', 'miniapp']) {
      expect(read(`../layouts/${layout}.vue`)).toContain('<AppOfflineBanner />')
    }
  })

  it('не показывается при загрузке страницы без сети — только после события offline', () => {
    // Признак преждевременного показа: начальное значение флага равно true.
    const composable = read('../composables/useOnline.ts')
    expect(composable).toMatch(/const offline = ref\(false\)/)
    expect(composable).toMatch(/addEventListener\('offline'/)
  })

  it('объявляет обрыв доступным для скринридера, а не только цветом', () => {
    const component = read('../components/AppOfflineBanner.vue')
    expect(component).toContain('role="alert"')
    // Цвет не должен быть единственным носителем смысла — нужен текст.
    expect(component).toMatch(/Нет соединения/)
  })

  it('подтверждает восстановление связи, но не навсегда', () => {
    const component = read('../components/AppOfflineBanner.vue')
    expect(component).toMatch(/Соединение восстановлено/)
    // setTimeout без таймаута оставил бы сообщение висеть навсегда
    expect(component).toMatch(/setTimeout\(\(\) => \{/)
  })
})