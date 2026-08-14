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

Текущий статус: **Этапы 0–4 (ядро)** ✅🟡 — скелет, БД/ядро, авторизация/RBAC, каталог+цены, импорт CSV (Celery).

| Этап | Статус | Примечание |
|---|---|---|
| 0 — Скелет + Docker | ✅ | compose/Makefile (pre-commit/CI нет) |
| 1 — БД и ядро BE | ✅ | модели, миграции, конфиг, structlog |
| 2 — Авторизация + RBAC | ✅ | JWT/сессии, `require_role`, seed-менеджер |
| 3 — Каталог и цены | 🟡 | PricingService + каталог API + страница каталога готовы; **нет Redis-кэша с тегами** |
| 4 — Импорт CSV (Celery) | 🟡 | ядро готово (upload→polars→upsert→PriceHistory→отчёт ошибок→MinIO); отложены photo-ZIP/миниатюры, rollback, price-change-digest |
| 5 — Frontend | 🟡 | login/catalog/layouts/middleware готовы; **нет manager-страниц и детальной карточки товара** |
| 6–12 | ⬜ | заявки, экспорт, менеджер-панель, hardening, observability, деплой, TG Mini App |

**Кандидаты на следующий этап** (выбрать в новой сессии):
- **Этап 5 (frontend)** — manager-страницы (особенно `/manager/import`, потребляющая эндпоинт Этапа 4) + `/product/[sku]`;
- **Этап 3 gap** — слой Redis-кэша каталога/цен с инвалидацией по тегам;
- **Этап 4 deferred** — photo-ZIP+миниатюры, rollback версии, `PRICE_CHANGED_DIGEST`.

---

## 📌 Принципы работы с кодом

1. **Сначала документ — потом код.** См. `ARCHITECTURE_PLAN.md` §21.
2. **Чистая архитектура** (api → services → repositories → models). См. §4.
3. **API-first:** контракты эндпоинтов описаны в §6; реализация им соответствует.
4. **Безопасность:** см. чек-лист §11 (JWT, RBAC, rate-limit, валидация загрузок).

---

## Лицензия / контакты

Заказчик: (уточняется). Хостинг: Беларусь. Домен: `.by` (уточняется).
