/**
 * Опции запуска Chromium, общие для playwright.config.ts и global-setup.ts.
 *
 * В контейнере web браузера Playwright нет (Makefile → test-e2e ставит
 * системный chromium через apk и передаёт путь в
 * PLAYWRIGHT_CHROMIUM_EXECUTABLE). Если global-setup проигнорирует эту
 * переменную, он упадёт на `chromium.launch()` раньше, чем начнутся тесты,
 * и весь набор молча не запустится — поэтому читать её надо в обоих местах.
 */
export function chromiumLaunchOptions(): { executablePath?: string } {
  const executable = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?.trim()
  return executable ? { executablePath: executable } : {}
}