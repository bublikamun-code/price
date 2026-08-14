# Статус исправлений аудита

Источник: вставленный отчёт аудита этапов 0–5. Проверено относительно текущего кода и канона `ARCHITECTURE_PLAN.md` (§6, §11; документ читался поиском по секциям).

## Классификация

| Пункт | Статус | Результат |
|---|---|---|
| Refresh доступен JavaScript | ✅ исправлено | Удалён из JSON-контракта, Pinia и frontend-cookie; refresh/rotation только через httpOnly cookie. |
| Logout не удаляет cookies | ✅ исправлено | Ответ удаляет access/refresh cookies; сессия отзывается. |
| Upload читает весь файл до лимита | ✅ исправлено частично | Чтение ограничено `limit + 1`; полный streaming в S3 остаётся отдельной задачей. |
| Валюта обрезается до 3 символов | ✅ исправлено | Строгая проверка ровно трёх латинских букв, иначе 422. |
| CSRF для cookie auth | ⏳ актуально | Требует отдельного согласованного внедрения double-submit во все mutating-запросы и frontend. |
| HS256/default secret вместо RS256 | ⏳ актуально | Канон требует RS256 в production; нужны схема хранения/передачи ключей и обновление deployment secrets. |
| SQL в роутерах | ⏳ актуально | Подтверждено в manager prices; нужен поэтапный рефакторинг services/repositories. |
| Каталог vs §6, response envelopes | ⏳ требует отдельной сверки | Контракт объёмный; не менялся без полного endpoint-by-endpoint решения. |
| ILIKE вместо FTS/pg_trgm | ⏳ актуально | Подтверждено в `repositories/catalog.py`. |
| N+1 каталога | ⏳ требует профилирования | Старый отчёт недостаточен как доказательство после изменений кода. |
| Upload только по расширению | ✅ исправлено | До S3 проверяются allowlist MIME, UTF-8/BOM, отсутствие NUL и обязательный CSV-заголовок `sku`/`name`; политика зафиксирована в §7.1. |
| UUID v4 вместо v7 | ⏳ требует миграционного решения | Изменение идентификаторов затрагивает модели/БД/совместимость. |
| README устарел | ✅ подтверждено | Manager import и product page уже существуют; дорожная карта требует обновления после завершения текущего пакета. |
| Production TLS | ⏳ runtime/deployment | Нельзя подтвердить статическим кодом без окружения. |
| Redis rate limiter | ✅ исправлено | slowapi использует общее Redis-хранилище счётчиков, URL собирается из `REDIS_HOST/PORT/DB`; покрыто конфигурационными тестами. |
| Dead code, schema drift | ⏳ отдельный аудит | Требуют отдельной ограниченной сверки; не смешивались с rate-limiter пакетом. |

## Изменённые файлы

- `apps/api/app/api/v1/auth.py`
- `apps/api/app/schemas/auth.py`
- `apps/api/app/api/v1/manager/prices.py`
- `apps/api/tests/test_import_csv.py`
- `ARCHITECTURE_PLAN.md`
- `apps/api/tests/test_auth.py`
- `apps/api/app/core/config.py`
- `apps/api/app/core/limiter.py`
- `apps/api/tests/test_health.py`
- `apps/web/composables/useAuth.ts`
- `apps/web/plugins/auth.session.ts`
- `apps/web/types/api.ts`
- `IMPLEMENTATION_STATUS.md`

## Последний пакет: Redis-backed rate limiter

- Канон: в `ARCHITECTURE_PLAN.md` §11 уточнено общее Redis-хранилище счётчиков между API workers.
- Реализация: `Settings.redis_url` собирает URL из существующих `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`; slowapi использует этот URL вместо process-local memory storage.
- Тесты: `apps/api/tests/test_health.py` проверяет сборку Redis URL и Redis backend limiter-а без подключения к production-инфраструктуре.
- Миграции, новые секреты и продуктовые решения не требуются.

## Проверки

- `python3 -m compileall -q apps/api/app apps/api/tests` — успешно после Redis rate-limiter пакета.
- `python3 -m pytest apps/api/tests/test_health.py -q` — не запущен: `pytest` отсутствует в системном Python.
- `python3 -m ruff check apps/api/app/core/config.py apps/api/app/core/limiter.py apps/api/tests/test_health.py` — не запущен: `ruff` отсутствует в системном Python.
- Frontend typecheck не требуется: frontend в этом пакете не менялся.
- Git commit не создавался; корень не является Git working tree.

## Аудит безопасности и качества кода — 2026-08-14

### Выполнено

- Восстановлена безопасная внутренняя передача refresh_token (cookie rotation без выдачи в JSON)
- Добавлен auth-тест
- Удалены неиспользуемые импорты и типы
- Исправлены расхождения authHeaders и useProductPhoto
- Backend: 137/137 pytest passed
- Alembic: 1 head
- compileall: exit 0
- Frontend typecheck: 0 ошибок
- Исправлен nullable chart: в `apps/web/pages/catalog/[sku].vue` строка 294, v-if дополнен `&& chart`

### Блокер — закрыт (2026-08-14, след. сессия)

- **ESLint 9 / Flat Config — решено.** Причина падения была не в конфиге: `@nuxt/eslint` →
  `eslint-flat-config-utils` использует `Object.groupBy` (появился в Node 21+), а контейнер web
  работал на Node 20 (`TypeError: Object.groupBy is not a function`).
  Решение: базовый образ web поднят до Node 22 (`apps/web/Dockerfile` + `engines.node >=22`),
  контейнер пересобран с чистым `node_modules`. Линтер заработал и выявил накопившиеся
  34 errors (`no-explicit-any`) + 64 warnings — устранены: типизация через `unknown` +
  helper `apps/web/utils/errors.ts` (`getErrorMessage`/`getErrorStatus`), автофикс форматирования.
  Итог: `npm run lint` — 0 problems (exit 0), `npm run typecheck` — 0 ошибок (exit 0).
  ESLint возвращён в пайплайн (`make lint`).
