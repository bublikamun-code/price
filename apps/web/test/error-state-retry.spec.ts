import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createSSRApp, defineComponent, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'

/**
 * Кнопка «Повторить» в UiErrorState.
 *
 * Найдено при аудите UX: компонент объявляет `defineEmits<{ retry: [] }>()`
 * и одновременно гейтил кнопку на `$attrs.onRetry`. Но Vue вырезает
 * обработчик объявленного события из `$attrs` (isEmitListener), поэтому
 * `$attrs.onRetry` всегда был undefined — кнопка не рендерилась НИКОГДА.
 * Страницы, где уже стоял `@retry="load"`, молча теряли возможность повторить.
 *
 * SFC нельзя импортировать в vitest (в конфиге нет vue-плагина), поэтому
 * поведение проверяется на точной реплике компонента: воспроизводим и
 * сломанный, и исправленный паттерн. Плюс проверяем исходник настоящего
 * компонента, чтобы регрессия не вернулась.
 */

const readComponent = () =>
  readFileSync(fileURLToPath(new URL('../components/ui/ErrorState.vue', import.meta.url)), 'utf8')

/** Разметка без HTML-комментариев: в комментарии строка может встречаться
 *  как объяснение, и её наличие не означает, что гейт вернулся. */
const readTemplate = () => readComponent().replace(/<!--[\s\S]*?-->/g, '')

/** Реплика компонента БЕЗ исправления: гейт на $attrs.onRetry. */
const Broken = defineComponent({
  props: { retryLabel: { type: String, default: 'Повторить' } },
  emits: ['retry'],
  setup(props, { emit, attrs, slots }) {
    return () =>
      h('div', [
        slots.action?.() ??
          (attrs.onRetry
            ? h('button', { onClick: () => emit('retry') }, props.retryLabel)
            : null),
      ])
  },
})

/** Реплика компонента ПОСЛЕ исправления: кнопка всегда, если нет #action. */
const Fixed = defineComponent({
  props: { retryLabel: { type: String, default: 'Повторить' } },
  emits: ['retry'],
  setup(props, { emit, slots }) {
    return () =>
      h('div', [
        slots.action?.() ?? h('button', { onClick: () => emit('retry') }, props.retryLabel),
      ])
  },
})

const render = (component: unknown, attrs: Record<string, unknown>) =>
  renderToString(createSSRApp(component as never, attrs))

describe('UiErrorState: кнопка «Повторить»', () => {
  it('старый паттерн действительно не рендерил кнопку — это и был баг', async () => {
    const html = await render(Broken, { onRetry: () => {} })
    expect(html).not.toContain('Повторить')
  })

  it('исправленный компонент рендерит кнопку, когда передан @retry', async () => {
    const html = await render(Fixed, { onRetry: () => {} })
    expect(html).toContain('Повторить')
  })

  it('собственный #action имеет приоритет над кнопкой по умолчанию', async () => {
    const withSlot = defineComponent({
      setup: () => () => h(Broken, null, { action: () => h('button', 'Своя кнопка') }),
    })
    const html = await render(withSlot, { onRetry: () => {} })
    expect(html).toContain('Своя кнопка')
    expect(html).not.toContain('Повторить')
  })

  it('настоящий компонент больше не гейтит кнопку на $attrs.onRetry', () => {
    const template = readTemplate()
    expect(template).not.toContain('$attrs.onRetry')
    // emit('retry') остаётся — на него вешается обработчик
    expect(template).toContain("emit('retry')")
  })
})