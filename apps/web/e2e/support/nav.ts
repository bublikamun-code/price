import type { Page } from '@playwright/test'

/**
 * Переход по странице с `waitUntil: 'domcontentloaded'`.
 *
 * Playwright по умолчанию ждёт `load` — то есть пока не подгрузятся ВСЕ
 * подресурсы, включая внешние шрифты с fonts.googleapis.com и SSE-поток
 * уведомлений. На стенде без устойчивого внешнего интернета (или при
 * подвисании стороннего CDN) это превращается в 60-секундный таймаут
 * на пустом месте: страница уже отрисована, а `load` так и не наступил.
 *
 * `domcontentloaded` + ожидания через `expect` дают тот же результат:
 * проверки всё равно авто-дожидаются нужных элементов, но не зависят от
 * сторонних ресурсов.
 */
export async function goto(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
}