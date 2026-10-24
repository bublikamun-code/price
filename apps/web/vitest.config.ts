import { configDefaults, defineConfig } from 'vitest/config'

// Vitest-конфиг нужен только ради одного правила: apps/web/e2e/** — это
// Playwright, а не vitest. По умолчанию vitest подхватывает все *.spec.ts
// и падает на их test.describe(), который у Playwright синхронный-но-другой.
// Сами юнит-тесты живут в apps/web/test/** и запускаются как раньше.
export default defineConfig({
  test: {
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})