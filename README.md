# B2B «Клиентский портал с динамическими прайс-листами»

Веб-приложение для B2B-продаж: личные кабинеты клиентов и менеджера,
динамические прайс-листы с персональными ценами, импорт CSV, заявки, уведомления.

> **Каноничные документы:** [`ARCHITECTURE_PLAN.md`](./ARCHITECTURE_PLAN.md) (v1.1) и [`SITEMAP.md`](./SITEMAP.md) (v1.0).
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
| Nginx (единый вход) | http://localhost:8080 |
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

Текущий статус: **Этапы 0–8** ✅ (кроме отложенных: PDF-экспорт §16.1 F и SSE-уведомлений §16 п.20) — ядро, авторизация/RBAC, каталог и персональные цены, импорт CSV, заявки, менеджер-панель и все экраны MVP (§16 п.20) реализованы.

| Этап | Статус | Примечание |
|---|---|---|
| 0 — Скелет + Docker | ✅ | compose/Makefile (pre-commit/CI нет) |
| 1 — БД и ядро BE | ✅ | модели, миграции, конфиг, structlog |
| 2 — Авторизация + RBAC | ✅ | JWT/сессии, `require_role`, seed-менеджер, CSRF double-submit |
| 3 — Каталог и цены | ✅ | PricingService, API и frontend каталога/карточки товара; Redis-кэш каталога, фильтров и рассчитанных цен с теговой инвалидацией; индексированный pg_trgm-поиск |
| 4 — Импорт CSV (Celery) | ✅ | upload→polars→upsert→PriceHistory→отчёт ошибок→MinIO и manager import UI; streaming upload в S3; rollback версии прайса (§16 п.14); photo-ZIP: webp thumb/large + матчинг к сериям + `series_photo` CSV (§16 п.17) |
| 5 — Frontend | ✅ | все экраны MVP: login, каталог/карточка, корзина/checkout, заявки, избранное, профиль, consent, уведомления (pull, колокольчик), массовое добавление, файлы + manager-страницы (§16 п.20) |
| 6–8 — Заявки и менеджер | ✅ | заявки клиента/менеджера; экспорт каталога CSV/XLSX (PDF отложен, §16 п.16); файловый архив `/files` + `/manager/files` (§16 п.18); клиенты/скидки/курсы/аудит (§16 п.19): `/manager/users` CRUD + temp-пароли + матрица скидок + fixed-rate, `/manager/currency`, `/manager/audit`; дозакрытие экранов (§16 п.20): дашборд (фича G, кэш 60 с), `/manager/catalog` + PATCH товара (аудит, инвалидация кэша), `/manager/brands` + фото серий, уведомления in-app pull, `/bulk-add` (фича B), `/consent` (п.10) |
| 9–12 | ⬜ | hardening, observability, деплой, TG Mini App |

**Ближайшие задачи / остаток:**
- **Hardening и поиск** — CSRF double-submit ✅, pg_trgm-индексы поиска ✅, RS256 + PEM-ключи для prod (§16 п.15) ✅; остаток — production TLS (проверяется при деплое, Этап 11); известный edge (найден при GUI-тесте 2026-08-20): 403 на login/refresh, если в браузере остался `refresh_token`, а `csrf_token`-cookie потерян — требуется решение в §16 (например, чистить стейл-куки при логине);
- **Импорт** — streaming upload в S3 ✅, rollback версии прайса ✅, photo-ZIP+миниатюры ✅;
- **Продуктовые сценарии** — экраны §16 п.20 ✅ (дашборд, manager-каталог/бренды, уведомления pull, bulk-add, consent); остаются: PDF-формат экспорта (weasyprint, §16.1 F), SSE-стрим уведомлений (отложено, §16 п.20), статическая страница `/privacy`;
- **Инфраструктура** — observability, production deployment и TG Mini App.

---

## 📌 Принципы работы с кодом

1. **Сначала документ — потом код.** См. `ARCHITECTURE_PLAN.md` §21.
2. **Чистая архитектура** (api → services → repositories → models). См. §4.
3. **API-first:** контракты эндпоинтов описаны в §6; реализация им соответствует.
4. **Безопасность:** см. чек-лист §11 (JWT, RBAC, rate-limit, валидация загрузок).

---

## Лицензия / контакты

Заказчик: (уточняется). Хостинг: Беларусь. Домен: `.by` (уточняется).
