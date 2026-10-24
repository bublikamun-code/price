// ============================================================
//  Playwright — E2E (§16 п.23).
//
//  Браузерные тесты идут ПРОТИВ ЖИВОГО СТЕКА, который поднимают
//  через docker compose (make up / make web-dev). Поэтому `webServer`
//  здесь намеренно НЕ задан: Playwright не должен ни поднимать, ни
//  пересобирать фронт — адрес приходит снаружи через E2E_BASE_URL.
//
//  Как это работает в проекте (см. Makefile → test-e2e):
//    NGINX_IP=$(docker inspect -f '{{...IPAddress}}' pp-nginx)
//    docker compose -f infra/docker-compose.yml --env-file .env exec \
//      -e E2E_BASE_URL="http://$$NGINX_IP" \
//      -e PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
//      web npx playwright test
//
//  По умолчанию (без env) baseURL — хостовый адрес того же единого входа:
//  порт берётся из DEV_NGINX_PORT в .env (по умолчанию 8080, в этом
//  стенде — 8081), потому что nginx слушает 80 только внутри compose-сети.
// ============================================================

import { defineConfig, devices } from '@playwright/test'
import { chromiumLaunchOptions } from './e2e/support/browser'

/** Адрес стенда. Внутри контейнера web — внутренний IP nginx. */
const baseURL = process.env.E2E_BASE_URL?.trim() || 'http://localhost:8081'

const isCI = !!process.env.CI

// Артефакты прогонов держим внутри e2e/, чтобы `eslint .` / `nuxt typecheck`
// не спотыкались о сгенерированный html-report.
const ARTIFACTS = './e2e/.artifacts'

export default defineConfig({
  testDir: './e2e',
  outputDir: `${ARTIFACTS}/test-results`,
  // 1 воркер: тесты ходят по общему стенду (общие данные в БД, rate-limit
  // на /auth/login в Redis). Параллельный прогон даёт взаимные флаки.
  fullyParallel: false,
  workers: 1,
  forbidOnly: isCI,
  // Ретраи выключены осознанно: стенд общий, а /auth/login ограничен
  // rate-limit'ом (RATE_LIMIT_LOGIN). Повтор упавшего теста съел бы ещё
  // одну попытку входа и мог докритит лимит для остальных. Причина падения
  // после первого прогона восстанавливается через `trace: retain-on-failure`.
  retries: 0,
  globalSetup: './e2e/global-setup.ts',
  // Общая потолковая рамка на тест; внутри — expect/action таймауты ниже.
  timeout: 60_000,
  expect: { timeout: 15_000 },

  reporter: isCI
    ? [['list'], ['html', { outputFolder: `${ARTIFACTS}/html-report`, open: 'never' }]]
    : [['list']],

  use: {
    baseURL,
    locale: 'ru-RU',
    timezoneId: 'Europe/Minsk',
    // Каталог и менеджский раздел верстаются под десктоп; дефолтные
    // 1280×720 попадают ровно на xl-брейкпоинт Tailwind, где часть
    // разметки ещё скрыта. Фиксируем осознанный десктопный размер.
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15_000,
    // На dev-стенде (make web-dev) первый заход на маршрут компилируется
    // на лету и легко уходит за 30 с; на prod-сборке запас просто не тратится.
    navigationTimeout: 60_000,
    // Главная ценность прогона на стенде — уметь понять, что сломалось.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        launchOptions: chromiumLaunchOptions(),
      },
    },
  ],
})