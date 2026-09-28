# B2B «Клиентский портал с динамическими прайс-листами»

Веб-приложение для B2B-продаж: личные кабинеты клиентов и менеджера,
динамические прайс-листы с персональными ценами, импорт CSV, заявки, уведомления.

> **Каноничные документы:** [`ARCHITECTURE_PLAN.md`](./ARCHITECTURE_PLAN.md) (v1.9) и [`SITEMAP.md`](./SITEMAP.md) (v1.0).
> Любое отклонение от них в коде — сначала правка документа, потом код (см. §21 архитектуры).

---

## 🧱 Структура monorepo

```
.
├── ARCHITECTURE_PLAN.md        # каноничная архитектура (БД, API, логика, решения)
├── SITEMAP.md                  # карта экранов (роуты, состав страниц)
├── README.md
├── Makefile                    # удобные команды
├── .env.example                # пример окружения → скопировать в .env
│
├── apps/
│   ├── api/                    # FastAPI backend (Python 3.12)
│   │   ├── app/
│   │   │   ├── main.py         # точка входа FastAPI
│   │   │   ├── core/           # config, security, logging, deps
│   │   │   ├── db/             # SQLAlchemy session + base
│   │   │   ├── models/         # ORM-модели (§5)
│   │   │   ├── schemas/        # Pydantic DTO
│   │   │   ├── repositories/   # доступ к данным
│   │   │   ├── services/       # бизнес-логика (use-cases)
│   │   │   ├── api/v1/         # роутеры (тонкие)
│   │   │   ├── tasks/          # Celery-таски (импорт CSV, ...)
│   │   │   ├── workers/        # Celery app config
│   │   │   └── bot/            # Telegram-бот
│   │   ├── alembic/            # миграции БД
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── web/                    # Nuxt 3 frontend (Vue 3 + TS + Tailwind)
│       ├── pages/              # file-based routing (см. SITEMAP §4)
│       ├── layouts/            # default / auth / client / manager / miniapp
│       ├── components/
│       ├── composables/
│       ├── middleware/         # auth.ts, role.ts
│       ├── assets/css/         # Tailwind + дизайн-система (§3)
│       ├── nuxt.config.ts
│       ├── tailwind.config.ts
│       └── Dockerfile
│
└── infra/                      # инфраструктура
    ├── docker-compose.yml      # dev (все сервисы)
    ├── docker-compose.prod.yml # prod-override
    ├── nginx/nginx.conf
    └── minio/init.sh           # создание бакетов
```

---

## 🚀 Быстрый старт (dev)

### Требования
- Docker 24+ и Docker Compose v2
- (опц.) Make

### Шаги
```bash
# 1. Склонировать и перейти в папку проекта
cd "Price web"

# 2. Подготовить окружение
cp .env.example .env
#    → отредактировать .env (особенно TELEGRAM_BOT_TOKEN в дальнейшем)

# 3. Поднять всю инфраструктуру
make up            # или: docker compose -f infra/docker-compose.yml up -d

# 4. Применить миграции БД
make migrate

# 5. (опц.) Наполнить тестовыми данными — когда seed будет готов
# make seed
```

### Адреса (dev)
| Сервис | URL |
|---|---|
| Web (клиент) | http://localhost:3000 |
| API (FastAPI) + Swagger | http://localhost:8000/docs |
| Nginx (единый вход) | http://localhost:8080 (override: `DEV_NGINX_PORT` в `.env` — напр. 8081 при конфликте портов с соседними проектами; аналогично `DEV_DB_PORT`/`DEV_REDIS_PORT`) |
| MinIO Console | http://localhost:9001 (minioadmin / minioadmin) |
| PostgreSQL | localhost:5432 (price / price_secret) |
| Redis | localhost:6379 |

### Частые команды
```bash
make logs          # логи всех сервисов
make ps            # статус
make down          # остановить
make api-shell     # зайти в контейнер api
make migrate-gen m="create users"   # сгенерировать миграцию
make test          # тесты
```

---

## 🛣️ Дорожная карта

Реализация идёт по этапам из [`ARCHITECTURE_PLAN.md` §15/§19](./ARCHITECTURE_PLAN.md).

Текущий статус: **Этапы 0–11.5 + PDF-экспорт + SSE-уведомления** ✅ — продуктовый backlog MVP пуст (все фичи §16.1 реализованы); в работе Этап 13 (нативные клиенты iOS + Android), из крупного также остаётся Этап 12 (TG Mini App, post-MVP) и пост-MVP-инфра (Loki/Tempo/Uptime Kuma, WAL-G, registry). Фактический выезд на VPS — по RUNBOOK.

| Этап | Статус | Примечание |
|---|---|---|
| 0 — Скелет + Docker | ✅ | compose/Makefile (pre-commit/CI нет) |
| 1 — БД и ядро BE | ✅ | модели, миграции, конфиг, structlog |
| 2 — Авторизация + RBAC | ✅ | JWT/сессии, `require_role`, seed-менеджер, CSRF double-submit |
| 3 — Каталог и цены | ✅ | PricingService, API и frontend каталога/карточки товара; Redis-кэш каталога, фильтров и рассчитанных цен с теговой инвалидацией; индексированный pg_trgm-поиск |
| 4 — Импорт CSV (Celery) | ✅ | upload→polars→upsert→PriceHistory→отчёт ошибок→MinIO и manager import UI; streaming upload в S3; rollback версии прайса (§16 п.14); photo-ZIP: webp thumb/large + матчинг к сериям + `series_photo` CSV (§16 п.17) |
| 5 — Frontend | ✅ | все экраны MVP: login, каталог/карточка, корзина/checkout, заявки, избранное, профиль, consent, уведомления (pull, колокольчик), массовое добавление, файлы + manager-страницы (§16 п.20) |
| 6–8 — Заявки и менеджер | ✅ | заявки клиента/менеджера; экспорт каталога CSV/XLSX (PDF отложен, §16 п.16); файловый архив `/files` + `/manager/files` (§16 п.18); клиенты/скидки/курсы/аудит (§16 п.19): `/manager/users` CRUD + temp-пароли + матрица скидок + fixed-rate, `/manager/currency`, `/manager/audit`; дозакрытие экранов (§16 п.20): дашборд (фича G, кэш 60 с), `/manager/catalog` + PATCH товара (аудит, инвалидация кэша), `/manager/brands` + фото серий, уведомления in-app pull, `/bulk-add` (фича B), `/consent` (п.10) |
| 9 — Hardening | ✅ | rollback версии прайса, rate limits + Redis, валидация файлов, CSRF-фикс стейл-кук (§16 п.21), 2FA TOTP для менеджера + журнал сессий с отзывом (§16 п.22); i18n исключён каноном (§16 п.9 — RU-only) |
| 10 — Observability и тесты | ✅ | `/metrics` (instrumentator) + Pushgateway для Celery; `make obs-up` — Prometheus+Grafana (2 дашборда)+Alertmanager (правила §12)+Pushgateway; E2E Playwright `make test-e2e` (9 сценариев §13); k6-скрипты `infra/k6/` (`make test-load[-import]`, нужен k6 на хосте); Loki/Tempo/Uptime Kuma и CI → Этап 11 (§16 п.23) |
| 11 — Деплой в prod | ✅ (комплект) | `nginx.prod.conf` (TLS1.3+HSTS, :80→301, /metrics allow приватные сети), prod-overlay харднинг (порты db/redis/minio закрыты, фиксы merge-багов), `make prod-up/prod-down/prod-logs/prod-migrate`, `make backup` (pg_dump -Fc, retention 30 д.) + `backup-list`, `make gen-self-signed-certs`, `docs/RUNBOOK.md`, CI `.github/workflows/ci.yml` (lint→test→security→build; registry/WAL-G — пост-MVP, §16 п.24) |
| 11.5 — 1С-заглушки | ✅ | subroute `/api/integrations/1c` (§18): 4 эндпоинта → 501; `X-Integration-Token` (401) + IP-allowlist CIDR (403), пустой токен → 503; DTO `schemas/commerceml/`; 27 тестов |
| 12 | ⬜ | TG Mini App (post-MVP) |
| 13 | 🚧 | Нативные клиенты iOS + Android (§16 п.36): общее KMP-ядро `core/` ✅ (26 тестов на общих фикстурах, `make mobile-test`), native auth в v2 (`clientType=NATIVE`, refresh в теле, ротация + reuse detection) ✅, v2 media resources (§16 п.37) ✅, UI первой версии (вход/прайс/каталог): iOS **собирается и линкуется** против настоящего KMP-фреймворка (`xcodebuild` → `BUILD SUCCEEDED`), но ещё ни разу не запускался — на машине нет iOS Simulator runtime; Android написан и выверен по сигнатурам ядра, но **не компилировался** (нет Android SDK). Подробности и список непроверенного — `ios/PriceWebApp/README.md` и `android/README.md`. Контракт — `docs/NATIVE_API_CONTRACT.md` |

**Ближайшие задачи / остаток:**
- **Hardening и поиск** — CSRF double-submit ✅, pg_trgm-индексы поиска ✅, RS256 + PEM-ключи для prod (§16 п.15) ✅, edge со стейл-куками при логине закрыт (§16 п.21), 2FA TOTP (фича H) ✅ и журнал сессий с отзывом (фича I) ✅ (§16 п.22); остаток — production TLS (проверяется при деплое, Этап 11);
- **Импорт** — streaming upload в S3 ✅, rollback версии прайса ✅, photo-ZIP+миниатюры ✅;
- **Продуктовые сценарии** — экраны §16 п.20 ✅ (дашборд, manager-каталог/бренды, bulk-add, consent); `/privacy` ✅; PDF-экспорт ✅ (§16 п.25); **SSE-стрим уведомлений ✅ (§16 п.26)** — realtime-колокольчик с fallback-poll; продуктовый backlog пуст, из крупного остаётся только Этап 12 (TG Mini App, post-MVP);
- **Инфраструктура** — observability ✅ (§16 п.23: метрики, дашборды, алёрты, E2E, k6-скрипты); prod-комплект ✅ (§16 п.24: TLS-конфиг, бэкапы, RUNBOOK, CI, 1С-заглушки; фактический прогон CI и выезд на VPS — при деплое); остаются: Loki/Tempo/Uptime Kuma и WAL-G (пост-MVP), TG Mini App (Этап 12).

---

## 📌 Принципы работы с кодом

1. **Сначала документ — потом код.** См. `ARCHITECTURE_PLAN.md` §21.
2. **Чистая архитектура** (api → services → repositories → models). См. §4.
3. **API-first:** контракты эндпоинтов описаны в §6; реализация им соответствует.
4. **Безопасность:** см. чек-лист §11 (JWT, RBAC, rate-limit, валидация загрузок).

---

## Лицензия / контакты

Заказчик: (уточняется). Хостинг: Беларусь. Домен: `.by` (уточняется).
