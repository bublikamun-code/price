# 🏗️ B2B «Клиентский портал с динамическими прайс-листами»
## Архитектурный документ и Roadmap разработки

> **Роль документа:** Мастер-план (Technical Design Document + RFC), на основе которого ведётся пошаговая реализация. Документ расширяет исходное ТЗ и закрывает пробелы (security, edge-cases, observability, deploy).
>
> **Статус:** v1.4 — готов к передаче команде / ИИ-ассистенту.
> **Дата:** 2026-08-17

> ## ⚠️ ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ (обязательно для ИИ и разработчиков)
>
> **Этот файл (`ARCHITECTURE_PLAN.md`) + `SITEMAP.md` — каноничное описание системы.** Любые отклонения от него в ходе реализации недопустимы без отражения изменений здесь.
>
> **Правило работы (встроить в промпт нейросети):**
> 1. Перед началом любой задачи — прочитать этот файл целиком + `SITEMAP.md`.
> 2. Если в ходе работы выяснилось, что нужно **отклониться** от спроектированного (другой подход, другая таблица, другой эндпоинт) ИЛИ **добавить** новую сущность/фичу/поле:
>    - **СНАЧАЛА** обновить соответствующий раздел этого документа (Decisions Log §16, схему БД §5, API §6, Roadmap §15/§19 и т.д.).
>    - **ЗАТЕМ** писать код по обновлённой спеке.
> 3. Запрещено «молчаливо» менять архитектуру в коде — расхождение кода и документа = баг.
> 4. Версия документа инкрементируется при каждом изменении (v1.1 → v1.2...), значимые изменения фиксируются в §16 (Decisions Log) новой строкой.
> 5. Если требование неоднозначно — задать вопрос заказчику (§16 «Ожидают подтверждения»), не додумывать молча.

---

## 📋 СОДЕРЖАНИЕ

1. [Анализ исходного ТЗ и перечень дополнений](#1-анализ-исходного-тз-и-перечень-дополнений)
2. [Технологический стек с аргументацией](#2-технологический-стек-с-аргументацией)
3. [Дизайн-система (UI/UX)](#3-дизайн-система-uiux)
4. [Архитектура системы (High-Level)](#4-архитектура-системы-high-level)
5. [Схема базы данных](#5-схема-базы-данных)
6. [REST API спецификация](#6-rest-api-спецификация)
7. [Асинхронный импорт CSV и генерация цен на лету](#7-асинхронный-импорт-csv-и-генерация-цен-на-лету)
8. [Ценообразование: матрица скидок и мультивалютность](#8-ценообразование-матрица-скидок-и-мультивалютность)
9. [Модуль заявок и уведомлений](#9-модуль-заявок-и-уведомлений)
10. [Файловое хранилище (S3/MinIO) и медиа](#10-файловое-хранилище-s3minio-и-медиа)
11. [Безопасность (Security Checklist)](#11-безопасность-security-checklist)
12. [Observability: логи, метрики, мониторинг](#12-observability-логи-метрики-мониторинг)
13. [Тестирование](#13-тестирование)
14. [Деплой и инфраструктура](#14-деплой-и-инфраструктура)
15. [Roadmap разработки по этапам](#15-roadmap-разработки-по-этапам)
16. [Принятые решения (Decisions Log)](#16-принятые-решения-decisions-log)
17. [Модуль курсов валют НБ РБ](#17-модуль-курсов-валют-нб-рб-новое-по-решению-п1-и-п7)
18. [Подготовка к интеграции с 1С](#18-подготовка-к-интеграции-с-1с-новое-по-решению-п12)
19. [Корректировки к Roadmap](#19-корректировки-к-roadmap-по-итогам-решений)
20. [Центр уведомлений (Notification Hub)](#20-центр-уведомлений-notification-hub)
21. [Управление изменениями (Change Management)](#21-управление-изменениями-change-management)

---

## 1. Анализ исходного ТЗ и перечень дополнений

### ✅ Что уже хорошо раскрыто в исходном ТЗ
- Ролевая модель (RBAC), закрытая регистрация B2B.
- Два механизма ценообразования (процент по бренду + жёсткая цена из CSV).
- Структура CSV, soft-delete, заморозка цен в заказе.
- Асинхронный импорт через Celery/Redis.
- Стек: FastAPI + PostgreSQL + Vue/React + S3.
- Готовность к Telegram Mini App.

### ➕ Что НЕ раскрыто и добавлено в этот документ
| # | Тема | Решение в документе |
|---|------|---------------------|
| 1 | Авторизация: механика токенов, refresh, истечение сессии | §6, §11 — JWT access + refresh, httpOnly cookies |
| 2 | Управление пользователями менеджером (CRUD, сброс пароля) | §5, §6 — `User` + эндпоинты менеджера |
| 3 | Валидация и формат CSV (разделитель, кодировка, BOM) | §7 — строго специфицирован |
| 4 | Стратегия разрешения конфликтов при импорте (Upsert vs Replace) | §7 — `IMPORT_MODE` (upsert / replace / archive_missing) |
| 5 | Кэширование (каталог, фильтры, цены) | §4, §12 — Redis cache + invalidation |
| 6 | Полнотекстовый поиск по десяткам тысяч SKU | §5, §6 — PostgreSQL GIN + `tsvector` / pg_trgm |
| 7 | Обработка изображений (превью, webp, водяной знак) | §10 — Pillow + форматы |
| 8 | Лимиты загрузок (anti-abuse, rate-limit) | §11 — slowapi (rate-limit) + quotas |
| 9 | Аудит действий менеджера (кто сменил цену/скидку) | §5 — таблица `AuditLog` |
| 10 | Версионирование прайсов (откат на предыдущий) | §5 — `PriceListVersion` |
| 11 | i18n (RU/EN), формат чисел/дат | §4, §15 (Этап 8) |
| 12 | Тестовая стратегия (unit/integration/e2e) | §13 |
| 13 | CI/CD, миграции, бэкапы | §14 |
| 14 | Обработка ошибок и единый формат API-ответов | §6 — envelope `{data, meta, error}` |
| 15 | WebSocket / SSE для realtime-уведомлений | §9 — SSE для менеджера |
| 16 | Telegram Mini App: подготовка API | §6 — отдельный `/m/**` subroute + tg-auth |
| 17 | Cookie/согласие/GDPR-lite для B2B | §11 |
| 18 | Здоровье сервиса (`/healthz`, readiness probe) | §12 |

---

## 2. Технологический стек с аргументацией

### Backend
| Компонент | Выбор | Почему |
|-----------|-------|--------|
| Язык | **Python 3.12+** | async-native, огромная экосистема для парсинга и работы с PDF/изображениями. |
| Framework | **FastAPI** | Async I/O, авто-документация OpenAPI, Pydantic v2 для валидации, типизация. |
| ORM | **SQLAlchemy 2.0 (async)** + **Alembic** | Зрелая ORM с async-поддержкой; Alembic — миграции. |
| Валидация | **Pydantic v2** | Нативно интегрирована в FastAPI, fastest в Python. |
| Background | **Celery + Redis 7** | Гарантированная доставка задач, ретраи, inspect для мониторинга. Альтернатива — ARQ (легче, но менее зрелый). |
| Парсинг CSV | **`polars`** (основной) / `pandas` | Polars в 5–10× быстрее pandas на больших CSV, многопоточный, low-memory. |
| Auth | **`python-jose` (JWT)** + `passlib[bcrypt]` | Стандарт; bcrypt для хэширования паролей. |
| Rate limiting | **`slowapi`** | Простая интеграция с FastAPI. |
| PDF-генерация | **`weasyprint`** или **`reportlab`** | weasyprint — HTML→PDF (удобно для красивых каталогов). |
| Excel | **`openpyxl`** (xlsx) | Корректный `.xlsx` с форматированием. |
| Логирование | **`structlog`** | JSON-логи, удобны для агрегации. |

### Frontend
| Компонент | Выбор | Почему |
|-----------|-------|--------|
| Framework | **Vue 3 + Nuxt 3** | Nuxt даёт SSR/SSG, авто-роутинг, слой `useFetch` для типизированных API; отлично работает как Telegram Mini App. *Альтернатива:* React + Next.js. **Рекомендация — Nuxt 3.** |
| Язык | **TypeScript** | Строгая типизация, генерация типов из OpenAPI (`openapi-typescript`). |
| UI Kit | **Tailwind CSS + Headless UI + Radix-Vue / shadcn-vue** | Плоский воздушный стиль, мягкие цвета (см. §3). |
| Таблицы | **`tanstack/vue-table`** + **виртуальный скролл** (`@tanstack/vue-virtual`) | 10k+ строк без тормозов. |
| State | **Pinia** | Официальный store Vue 3. |
| Изображения | **`vue-easy-lightbox`** (zoom/lightbox), `<NuxtImg>` (webp/resize) | Лёгкий lightbox с zoom. |
| Формы | **`vee-validate` + `zod`** | Типобезопасная валидация. |
| Уведомления | **`vue-sonner`** (toasts) | Современные тосты. |
| i18n | **`@nuxtjs/i18n`** | RU/EN. |

### База данных и инфраструктура
| Компонент | Выбор | Почему |
|-----------|-------|--------|
| БД | **PostgreSQL 16** | JSONB (для матрицы скидок), GIN-индексы для поиска, `pg_trgm` для нечёткого поиска, надёжность. |
| Кэш/Брокер | **Redis 7** | Кэш каталога, брокер Celery, pub/sub для realtime. |
| Object storage | **MinIO** (S3-совместимый) | Self-hosted S3; seamless миграция на AWS S3/Yandex S3 без изменения кода. |
| Reverse proxy | **Nginx** или **Caddy** (Caddy — авто-TLS) | TLS, static, rate limit. |
| Контейнеризация | **Docker + docker-compose** (dev), **Docker Swarm / k8s** (prod) | Стандарт. |
| Monitoring | **Grafana + Prometheus + Loki** | Метрики + логи + трейсинг. Tempo для трейсов (OpenTelemetry). |
| Бэкапы | **`pgbackrest`** + **MinIO versioning** | PITR для PostgreSQL. |

---

## 3. Дизайн-система (UI/UX)

> Принципы: **плоский, воздушный, минимализм, мягкие цвета, плитка (card-based).**

### Палитра (soft / pastel)
```
Background canvas : #F7F9FC  (очень светло-серо-голубой)
Surface / card    : #FFFFFF
Surface elevated  : #FFFFFF + soft shadow (0 4px 20px rgba(43,57,83,0.06))
Border            : #E6EAF0
Primary accent    : #5B8DEF  (мягкий сине-фиолетовый)
Primary hover     : #4A7DD8
Secondary accent  : #8B7EE6 (лаванда)
Success (in stock): #4CAF85  (приглушённый зелёный)
Warning (preorder): #F2B33D
Danger (archived) : #E26D6D
Text primary      : #1F2937
Text secondary    : #6B7280
Text muted        : #9CA3AF
```

### Типографика
- Шрифт: **Inter** (.variable), вторичный — **Manrope** (для заголовков).
- Размеры: 12/14/16/18/24/32px. Межстрочный — 1.5–1.6 для воздушности.

### Карточки / Плитка
- `border-radius: 16px`, padding 20–24px, мягкая тень.
- Hover: лёгкий lift (`translateY(-2px)`), усиление тени.
- Активные фильтры — чипы (pills) с возможностью удаления.

### Компоненты каталога
- **Вид «Плитка»** (по умолчанию): карточка с фото серии сверху, артикул, наименование, бейдж бренда, статус, цена.
- **Вид «Таблица»** (toggle): плотная таблица для опытных покупателей.

### Анимации
- Framer-Motion-like transitions через CSS (`transition: 200ms cubic-bezier(0.4, 0, 0.2, 1)`).
- Skeletons при загрузке, shimmer-эффект.
- Микро-взаимодействия на кнопках (ripple, scale).

### Адаптивность
- Mobile-first breakpoints: 640 / 768 / 1024 / 1280.
- На мобильных — bottom-sheet для фильтров, sticky-корзина внизу.

---

## 4. Арххитектура системы (High-Level)

```
                         ┌─────────────────────────┐
                         │   Nginx / Caddy (TLS)   │
                         └────────────┬────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
      ┌───────▼────────┐      ┌───────▼────────┐      ┌───────▼────────┐
      │  Nuxt 3 SSR    │      │  FastAPI API   │      │  SSE endpoint  │
      │  (Frontend)    │─────▶│  (REST + OAS)  │      │  /notifications│
      └────────────────┘      └───────┬────────┘      └────────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
        ┌───────▼───────┐     ┌───────▼────────┐    ┌───────▼────────┐
        │ PostgreSQL 16 │     │  Redis (cache  │    │    Celery      │
        │  (primary)    │     │   + broker)    │    │   workers ×N   │
        └───────────────┘     └────────────────┘    └───────┬────────┘
                                                              │
                                                      ┌───────▼────────┐
                                                      │  MinIO (S3)    │
                                                      │ photos, pdfs,  │
                                                      │ generated csv  │
                                                      └────────────────┘

External integrations:
  • Telegram Bot API (уведомления менеджеру + Telegram Mini App auth)
  • SMTP (опционально — email-копии уведомлений)
```

### Слои FastAPI приложения (Clean Architecture)
```
app/
├── api/v1/            # Роутеры (тонкие, только HTTP)
│   ├── auth.py
│   ├── catalog.py     # прайс, фильтры, экспорт
│   ├── pricing.py     # калькуляция цен
│   ├── orders.py      # заявки
│   ├── files.py       # S3-выдача
│   ├── manager/       # эндпоинты менеджера (RBAC admin)
│   └── miniapp/       # Telegram Mini App
├── core/              # config, security (jwt), deps, logging
├── domain/            # бизнес-сущности и правила (pure python)
├── services/          # use-cases (application layer)
├── repositories/      # DAO / доступ к данным (SQLAlchemy)
├── models/            # ORM-модели
├── schemas/           # Pydantic DTO
├── tasks/             # Celery-таски (импорт CSV, генерация экспортов)
├── workers/           # Celery app config
└── main.py
```

### Принципы
- **API-first:** сначала пишем OpenAPI-спеку, потом код.
- **Stateless API:** сессии в JWT/Redis, легко масштабировать по горизонтали.
- **Кэширование:** каталог кэшируется в Redis с тегами; инвалидация при импорте/смене курса/смене скидок. Кэш fail-open: при недоступном Redis запрос обслуживается из БД («мимо кэша»), запись/инвалидация — best-effort.
- **API-versioning:** префикс `/api/v1/...`, для breaking changes — `/v2`.

---

## 5. Схема базы данных

> Используется PostgreSQL 16. Конвенция имён: `snake_case`, таблицы во множ. числе. Все сущности имеют `id` (UUID v7 — сортируемый), `created_at`, `updated_at`. Soft-delete через поле `deleted_at`.

### 5.1. ER-диаграмма (текстовая)

```
┌──────────────┐      ┌────────────────────┐      ┌──────────────────┐
│    users     │◀─────│   user_brands      │─────▶│    brands        │
│ (id, email,  │ 1..* │ (user_id, brand_id,│ *..1 │ (id, name, slug) │
│  role, ...)  │      │  discount_percent) │      └────────┬─────────┘
└──────┬───────┘      └────────────────────┘               │
       │ 1                                              1..│
       │                                                   │
       │ 1..                                          ┌─────▼──────────┐
┌──────▼───────┐                                  ┌───│   products     │
│   orders     │─┐                                │   │ (sku, name,    │
│ (status, ...)│ │ 1..                            │   │  series, ...)  │
└──────────────┘ │    ┌──────────────────┐        │   └──────┬─────────┘
                 │    │   order_items    │        │          │
                 └───▶│ (order_id,       │        │       FK │ brand_id
                      │  product_id,     │◀───────┤          │
                      │  qty, price_fix) │        │     ┌────▼─────────────┐
                      └──────────────────┘        │     │ price_list_ver-  │
                                                  │     │ sions (источник  │
                                                  │     │ импорта)         │
                                                  │     └──────────────────┘
                                                  │
                                                  │     ┌──────────────────┐
                                                  └────▶│   series         │
                                                        │ (id, name,      │
                                                        │  brand_id, photo)│
                                                        └──────────────────┘

Доп.: audit_log, file_assets, currencies, exchange_rates, notifications, sessions(refresh-tokens)
```

### 5.2. Описание ключевых таблиц

#### `users`
| column | type | note |
|---|---|---|
| id | UUID PK | |
| email | CITEXT UNIQUE | логин |
| password_hash | TEXT | bcrypt |
| full_name | TEXT | |
| company | TEXT | |
| phone | TEXT | |
| role | ENUM('CLIENT','MANAGER') | |
| is_active | BOOLEAN | менеджер может блокировать |
| created_at / updated_at | TIMESTAMPTZ | |

#### `brands`
| id | UUID PK |
| name | TEXT |
| slug | TEXT UNIQUE |

#### `user_brands` — матрица скидок
> Связь «Клиент → Бренд → Процент скидки».
| user_id | UUID FK |
| brand_id | UUID FK |
| discount_percent | NUMERIC(5,2) |
| **PK** | (user_id, brand_id) |
| updated_by | UUID FK → users (audit) |

#### `currencies` / `exchange_rates`
| code | CHAR(3) | USD, RUB, EUR... |
| rate_to_base | NUMERIC | например, 1 USD = base_unit |
| effective_from | DATE | history для аудита |
| is_active | BOOLEAN |

Менеджер задаёт глобальный курс валюты; цена вывода = `base_price * rate_to_base`.

#### `products`
| column | type | note |
|---|---|---|
| id | UUID PK | |
| sku | TEXT UNIQUE | артикул |
| name | TEXT | |
| series_id | UUID FK → series | |
| brand_id | UUID FK → brands | |
| base_price | NUMERIC(12,2) | базовая (из CSV, в base-валюте) |
| override_price | NUMERIC(12,2) NULL | жёсткая цена со скидкой из CSV (если задана — игнорируем процент) |
| stock_status | ENUM('IN_STOCK','PREORDER','OUT_OF_STOCK','ARCHIVED') | |
| price_list_version_id | UUID FK | источник импорта |
| deleted_at | TIMESTAMPTZ NULL | soft-delete |
| search_vector | TSVECTOR | GIN-индекс для полнотекстового поиска |
| attributes | JSONB NOT NULL DEFAULT '{}' | характеристики товара (фильтры, спецификации); наполняются при импорте |

**Индексы:**
- `UNIQUE (sku) WHERE deleted_at IS NULL`
- `GIN (search_vector)`
- `btree (brand_id), btree (series_id)`
- `pg_trgm GIN ON (name gin_trgm_ops)` — для поиска «как в Google».
- `pg_trgm GIN ON (sku gin_trgm_ops)` — поиск каталога `q` идёт по `sku ILIKE '%…%' OR name ILIKE '%…%'`; обе ветки ускоряются bitmap-сканом по trgm-индексам (сама семантика ILIKE-подстроки сохраняется).
- `GIN (attributes jsonb_path_ops)` — фильтрация по характеристикам через оператор `@>` (JSONB-контейнмент).

> **`attributes` (JSONB).** Гибкое хранилище спецификаций товара без жёсткой схемы: цвет, кол-во модулей, IP-рейтинг, габариты, материал и т.п. — состав зависит от категории (электротехника, корпуса, автоматы…). Пример:
> ```json
> {"modules": 12, "color": "Черный", "ip_rating": "IP40", "material": "пластик", "width_mm": 335}
> ```
> Числовые значения хранятся как числа (не строки) — для корректной фильтрации `attributes @> '{"modules": 12}'`. Текстовый поиск по характеристикам — через `attributes->>'key' ILIKE …`. Специфичные индексы под отдельные свойства добавляются точечно по мере необходимости.

#### `series`
| id | UUID PK |
| name | TEXT |
| brand_id | UUID FK |
| photo_key | TEXT | S3-ключ (связь по имени файла при импорте) |

#### `orders` / `order_items`
| orders.id | UUID PK |
| client_id | UUID FK |
| status | ENUM('NEW','IN_PROGRESS','SHIPPED','CANCELLED','COMPLETED') |
| currency_code | CHAR(3) | валюта заказа на момент |
| total_amount | NUMERIC |
| notes | TEXT |
| manager_id | UUID FK NULL | кто ведёт |

| order_items.id | UUID PK |
| order_id | FK |
| product_id | FK |
| product_snapshot | JSONB | снапшот {sku,name,brand} на момент заказа |
| quantity | INT |
| unit_price | NUMERIC | **жёстко зафиксированная цена со скидкой** |
| currency_code | CHAR(3) |

> ⚠️ **Заморозка цен:** `unit_price` сохраняется в момент оформления и НИКОГДА не пересчитывается. Если позже цена/скидка меняется — заказ не трогается.

#### `price_list_versions`
| id | UUID PK |
| uploaded_by | UUID FK (manager) |
| filename | TEXT |
| import_mode | ENUM('UPSERT','REPLACE','ARCHIVE_MISSING') |
| rows_total / rows_ok / rows_error | INT |
| status | ENUM('QUEUED','PROCESSING','DONE','FAILED') |
| error_log_key | TEXT | S3-ключ с детальным отчётом ошибок |
| started_at / finished_at | TIMESTAMPTZ |
| rolled_back_at / rolled_back_by | TIMESTAMPTZ / UUID FK NULL — отметка отката версии (когда и кто, §16 п.14) |

#### `file_assets` — каталоги/выгрузки для скачивания
| id | UUID PK |
| type | ENUM('BRAND_PDF','CUSTOM_CSV','PHOTO_ZIP','OTHER') |
| s3_key | TEXT |
| filename_display | TEXT |
| content_type | TEXT |
| size_bytes | BIGINT |
| brand_id | FK NULL |
| visibility | ENUM('PUBLIC','AUTHED','MANAGER_ONLY') |
| created_at | TIMESTAMPTZ |

#### `audit_log`
| id | UUID PK |
| actor_id | UUID FK |
| action | TEXT | e.g. `user.discount.update` |
| target_type, target_id | TEXT, UUID |
| before, after | JSONB |
| created_at | TIMESTAMPTZ |

#### `sessions` (refresh tokens)
| id | UUID PK |
| user_id | FK |
| refresh_token_hash | TEXT UNIQUE |
| user_agent, ip | TEXT |
| expires_at | TIMESTAMPTZ |
| revoked | BOOLEAN |

---

## 6. REST API спецификация

### Единый envelope ответа
```json
// success
{ "data": {...}, "meta": { "page": 1, "per_page": 50, "total": 1234 } }
// error
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "details": [...] } }
```

### Аутентификация
| Method | Path | Описание |
|---|---|---|
| POST | `/api/v1/auth/login` | Вход (email+password). Возвращает access JWT (15 мин) + refresh в httpOnly cookie (7 дней). |
| POST | `/api/v1/auth/refresh` | Обновить access. |
| POST | `/api/v1/auth/logout` | Отзыв refresh. |
| GET | `/api/v1/auth/me` | Текущий пользователь + матрица скидок. |
| PATCH | `/api/v1/auth/me` | Обновить свой профиль (partial update): `display_currency`, `price_digest_enabled`, `price_digest_sources` (§20.4). |

### Каталог и ценообразование
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/catalog/products` | Список с пагинацией/фильтрами. Query: `q`, `brand[]`, `series[]`, `stock`, `price_mode=retail\|discount`, `page`, `per_page`, `sort`. Цены рассчитываются на лету под текущего клиента. |
| GET | `/api/v1/catalog/products/{sku}` | Детализация товара + соседи по серии. |
| GET | `/api/v1/catalog/filters` | Доступные фильтры (бренды, серии, статусы) — используется для UI. |
| GET | `/api/v1/catalog/pricing/calculate` | Расчёт цены под клиента (для корзины). Body: `[{sku, qty}]` → `[{sku, unit_price, total}]`. |
| POST | `/api/v1/catalog/export` | Запуск генерации выгрузки каталога (метод приведён к POST — см. §16 п.16). Query: фильтры каталога (`q`, `brand_ids`, `series_ids`, `stock`, `price_calc_mode`) + `format=csv\|xlsx` (`pdf` → 422, отложен §16 п.16). Rate-limit: 10/час на клиента. Возвращает `{job_id}`. |
| GET | `/api/v1/catalog/export/{job_id}` | Статус генерации (`QUEUED/RUNNING/DONE/FAILED`, только владелец job) + presigned URL (5 мин) готового файла из S3 `csv-exports/`. |

### Заявки (клиент)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/orders` | Мои заявки. |
| POST | `/api/v1/orders` | Создать заявку. Body: `items:[{sku,qty}]`, `notes`. Сервер пересчитывает цены, делает snapshot, фиксирует. |
| GET | `/api/v1/orders/{id}` | Детали. |

### Менеджер (RBAC: `role=MANAGER`)
| Method | Path | Описание |
|---|---|---|
| POST | `/api/v1/manager/users` | Создать клиента (email, ФИО, компания). Система генерирует temp-пароль и показывает 1 раз. |
| GET \| PATCH \| `/api/v1/manager/users/{id}` | Профиль клиента. |
| POST | `/api/v1/manager/users/{id}/reset-password` | Сброс пароля. |
| PUT | `/api/v1/manager/users/{id}/discounts` | Сохранить матрицу скидок `[{brand_id, percent}]`. |
| POST | `/api/v1/manager/prices/import` | Загрузить CSV. Multipart. Body: `file`, `mode`, `currency`. Возвращает `version_id`. |
| GET | `/api/v1/manager/prices/versions` | История импортов + статус. |
| POST | `/api/v1/manager/prices/versions/{id}/rollback` | Откат версии (§16 п.14): товарам, существовавшим до версии, возвращаются цены из последнего снапшота `price_history` до неё; товары, впервые появившиеся в версии, архивируются (soft-delete, `ARCHIVE`). Разрешён только для последней DONE-версии; повторный откат/не-DONE/не последняя → 409. Инвалидирует кэш каталога тегами импорта. Возвращает карточку версии + счётчики `restored`/`archived`. |
| POST | `/api/v1/manager/brands` \| `/series` | CRUD брендов/серий. |
| GET \| PATCH | `/api/v1/manager/orders` | Все заявки, смена статусов. |
| POST | `/api/v1/manager/files` | Загрузить файл (PDF/CSV/ZIP). |
| GET | `/api/v1/manager/files` | Список. |
| DELETE | `/api/v1/manager/files/{id}` | Удалить. |
| POST | `/api/v1/manager/currencies/rate` | Установить курс валюты. |
| GET | `/api/v1/manager/audit` | Журнал аудита с фильтрами. |

### Файлы (общедоступные/авторизованные)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/files` | Список downloadable assets (PDF-каталоги брендов, выгрузки CSV). Фильтр по типу/бренду. |
| GET | `/api/v1/files/{id}/download` | Presigned URL (время жизни — 5 мин). |

### Realtime-уведомления (для менеджера)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/notifications/stream` | SSE-stream: новые заказы, ошибки импорта. Авторизация по JWT в query (`?token=`). |

### Telegram Mini App
| Method | Path | Описание |
|---|---|---|
| POST | `/api/m/v1/auth/telegram` | Авторизация по `initData` (Telegram WebApp signature). Возвращает JWT того же формата. |
| Прочие `/api/m/v1/...` | | Тонкое подмножество API (каталог, заявки), оптимизированное под мини-апп. |

### Health
| GET | `/healthz` | liveness (200 OK). |
| GET | `/readyz` | readiness (БД + Redis + S3 connectivity). |

---

## 7. Асинхронный импорт CSV и генерация цен на лету

### 7.1. Спецификация CSV
- **Кодировка:** UTF-8 (с BOM допустим — обрезаем).
- **Валидация загрузки до S3:** расширение `.csv`; multipart `Content-Type` из allowlist `text/csv`, `application/csv`, `application/vnd.ms-excel`, `text/plain`, `application/octet-stream` (последние три нужны для распространённых браузерных/OS-клиентов); содержимое должно декодироваться как UTF-8/UTF-8 BOM, не содержать NUL-байтов и иметь обязательный заголовок с колонками `sku` и `name` по алиасам §7.1. Клиентскому MIME не доверяем без проверки содержимого.
- **Разделитель:** `;` (европейский стандарт, безопасен для дробей с запятой). Допускается авто-детект `,` / `;` / `\t`.
- **Заголовок:** обязателен, регистронезависимый, поддерживаем алиасы (`Артикул | sku | article`).
- **Колонки:**
  1. `sku` (обязательно, уникально)
  2. `name` (обязательно)
  3. `series`
  4. `brand` (если бренда нет в БД — создаётся автоматически)
  5. `base_price` (Decimal, `.` или `,`)
  6. `discount_price` (опционально)
  7. `stock_status` (`IN_STOCK`/`PREORDER`/`OUT_OF_STOCK` или RU-алиасы)
  8. `series_photo` (имя файла, например `serie_a.jpg`)

### 7.2. Пайплайн импорта (Celery)

```
[Менеджер POST /import]
        │  (multipart upload, до ~100МБ)
        ▼
[FastAPI] ──сохраняет файл в S3 (tmp/) стримингом──▶ создаёт PriceListVersion(QUEUED)
        │  (upload_fileobj multipart, без буферизации целиком в памяти API;
        │   потоковая валидация: лимит 100МБ / UTF-8 / заголовок — до заливки)
        │
        └─▶ celery.send_task("import_price_list", version_id)

[Worker: import_price_list]
   1. download из S3 → streaming
   2. polars.read_csv(stream, schema=...)           # валидация на лету
   3. batch по 2000 строк:
        - нормализация (lowercase brand, валидация цены)
        - bulk upsert в `products` через ON CONFLICT (sku) DO UPDATE
        - связывание series_photo → series.photo_key
        - сборка отчёта ошибок (row, column, message)
   4. если mode=ARCHIVE_MISSING → UPDATE products SET deleted_at=now()
      WHERE sku NOT IN (импортированные) AND deleted_at IS NULL
   5. обновить PriceListVersion(status=DONE, rows_ok=..)
   6. ошибки → CSV-файл в S3, ключ в version.error_log_key
   7. invalidation Redis (теги: "catalog", "filters")
   8. SSE-уведомление менеджеру + Telegram-сообщение с краткой сводкой
```

> **MVP-scope (Этап 4, согласовано 2026-08-12):**
> - Шаги 7 (Redis-теги) и 8 (SSE/Telegram-digest) переносятся в следующие итерации.
> - `import_mode.REPLACE` на MVP трактуется как `ARCHIVE_MISSING` (upsert + архивация отсутствующих). Финальная семантика REPLACE (полный сброс каталога) — отдельная задача.
> - Задача `import_price_list` идемпотентна: стартует только при `status=QUEUED`, иначе no-op; слепой 3×-ретрай отключён (`autoretry_for=()`) — критические ошибки фиксируют `status=FAILED` и пишут отчёт.

### 7.3. Управление «длинной» операцией
- Прогресс читается как `(rows_ok + rows_error) / rows_total` (обновляется пачками). Отдельная колонка `rows_processed` не вводится — производная величина, чтобы не плодить схему.
- Возможен cancel через `celery.control.revoke`.
- Ретраи: 3 попытки с exponential backoff (на случай transient-ошибок БД) — общая настройка Celery; задача импорта явно отключает авто-ретрай (см. MVP-scope выше).

### 7.4. Пример: генерация цен «на лету»

> Весь каталог для клиента отдаётся **с уже пересчитанными ценами**. Расчёт идёт на стороне БД/сервиса, чтобы фронт не гонял лишнее.

**SQL (для каталога):**
```sql
SELECT
  p.*,
  s.photo_key,
  COALESCE(
    p.override_price,                                  -- 1) жёсткая цена из CSV (приоритет)
    CASE WHEN ub.discount_percent IS NULL
         THEN p.base_price                              -- 2) нет скидки → базовая
         ELSE ROUND(p.base_price * (1 - ub.discount_percent/100.0), 2)  -- 3) процент по бренду
    END
  ) * COALESCE(er.rate_to_base, 1) AS client_price,    -- 4) валютный курс
  p.base_price * COALESCE(er.rate_to_base,1) AS retail_price
FROM products p
JOIN brands b        ON b.id = p.brand_id
LEFT JOIN user_brands ub ON ub.brand_id = p.brand_id AND ub.user_id = :user_id
LEFT JOIN series s   ON s.id = p.series_id
LEFT JOIN exchange_rates er ON er.currency_code = :display_currency
                            AND er.effective_from <= now()
WHERE p.deleted_at IS NULL
  AND p.stock_status <> 'ARCHIVED'
  AND (:brand_id IS NULL OR p.brand_id = :brand_id)
ORDER BY p.name
LIMIT :limit OFFSET :offset;
```

**Service-слой (Python):**
```python
class PricingService:
    def __init__(self, repo, cache): ...

    async def get_catalog(self, user: User, filters: CatalogFilters) -> Page[ProductDTO]:
        cache_key = f"cat:{user.id}:{filters.hash()}"
        if cached := await self.cache.get(cache_key):
            return cached
        rows = await self.repo.fetch_catalog(user.id, filters)
        page = Page(rows, ...)
        await self.cache.set(cache_key, page, ttl=300, tags=["catalog", f"user:{user.id}"])
        return page
```

Инвалидация: при импорте/смене курса/смене скидок чистим тег `catalog`.

---

## 8. Ценообразование: матрица скидок и мультивалютность

### Приоритет источников цены (важно!)
```
1. override_price (жёстко из CSV)        ← если задано, используется ВСЕГДА
2. retail_price * (1 - user_discount[brand]/100)   ← иначе — процент по бренду
3. retail_price                            ← если у клиента нет скидки по бренду
```
Результат × exchange_rate → вывод в валюте клиента.

### Переключатель в UI
- Toggle «Розница / Со скидкой» хранится в `localStorage` и в query `price_mode`.
- При `retail` колонка цены = `retail_price`, скидка не применяется (даже если есть).
- При `discount` показываются обе: розница зачёркнута + цена со скидкой.

### Мультивалютность
- Базовая валюта прайса задаётся в настройках (`USD`).
- Менеджер заводит `exchange_rates` (история).
- Клиент в профиле выбирает display-валюту.
- Все суммы пересчитываются через актуальный курс.
- В `orders` фиксируется `currency_code` + сумма в ней (снапшот курса на момент заказа), чтобы история оставалась корректной.

---

## 9. Модуль заявок и уведомлений

### Жизненный цикл заявки
```
NEW → IN_PROGRESS → SHIPPED → COMPLETED
  │       │
  └───────┴──▶ CANCELLED (клиент или менеджер)
```

#### Допустимые переходы и инициаторы (уточнение для реализации)

| Из → В | Инициатор |
|---|---|
| `NEW → IN_PROGRESS` | менеджер |
| `NEW → CANCELLED` | клиент или менеджер |
| `IN_PROGRESS → SHIPPED` | менеджер |
| `IN_PROGRESS → CANCELLED` | клиент или менеджер |
| `SHIPPED → COMPLETED` | менеджер |
| `SHIPPED → CANCELLED` | менеджер (возврат) |
| `COMPLETED`, `CANCELLED` | терминальные (переходы запрещены) |

Клиент может только отменить свою заявку из `NEW`/`IN_PROGRESS` (`POST /orders/{id}/cancel`) либо создать новую; продвижение по статусу выполняет менеджер (`PATCH /manager/orders/{id}`). Запрещённый переход → `409 Conflict`.

### Создание заявки (транзакция)
1. Валидация позиций (есть в наличии / не архив).
2. **Расчёт цен под клиента** (через `PricingService`).
3. **Снапшот** товара (`product_snapshot` JSONB) + фиксация `unit_price`.
4. `INSERT orders`, `INSERT order_items ... ON CONFLICT DO NOTHING`.
5. Коммит.
6. Триггеры посткоммита (через `asyncio.create_task` / Celery):
   - SSE → менеджеру.
   - Telegram-сообщение менеджеру: «🆕 Заявка #X от {клиент}, {позиций} поз., {сумма}».
   - (опц.) Email клиенту «Заявка принята».

### Уведомления
- **Telegram Bot**: long-polling worker (отдельный процесс) или webhook. Шаблоны сообщений в Jinja2.
- **SSE на фронт-менеджера**: при новых заказах — звук + бейдж.
- **Статусы**: смена статуса менеджером → push клиенту в его кабинет + (опц.) Telegram.

---

## 10. Файловое хранилище (S3/MinIO) и медиа

### Бакеты
- `photos-series/` — фото серий (public-read через presigned).
- `pdf-catalogs/` — каталоги брендов.
- `csv-exports/` — генерируемые выгрузки (TTL 7 дней, lifecycle policy).
- `tmp-uploads/` — загружаемые CSV/ZIP (TTL 1 день).
- `error-logs/` — отчёты по неудачным импортам.

### Обработка фото
- На вход: ZIP с файлами `serie_a.jpg`, `serie_b.jpg`...
- Worker распаковывает, для каждого:
  - генерирует thumbnail (400×400 webp) и large (1200×1200 webp).
  - кладёт в S3 с ключом `photos-series/{slug}.webp`.
  - связывает с `series.photo_key` (по `series_photo` имени из CSV или по `series.name`).
- Фронт: `<NuxtImg>` отдаёт webp, `vue-easy-lightbox` — зум.

### Загрузка файлов клиентом
- Пресайнд-URL с TTL 5 мин (не отдаём файл напрямую через API — экономим bandwidth).

---

## 11. Безопасность (Security Checklist)

| Контроль | Реализация |
|---|---|
| Хэш паролей | bcrypt, cost=12. |
| JWT | RS256 в prod / HS256 в dev. RS256: PEM-ключи файлами, смонтированными в контейнеры read-only (`JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`, §16 п.15); access 15 мин, refresh 7 дней, rotate refresh. |
| Хранение refresh | хэш в `sessions`, httpOnly + Secure + SameSite=Lax cookie. |
| RBAC | зависимости FastAPI `Depends(require_role("MANAGER"))`. |
| CSRF | Для cookie-based auth — `SameSite=Lax` + double-submit: отдельная JS-readable cookie `csrf_token` и заголовок `X-CSRF-Token` должны совпадать (constant-time) на `POST/PUT/PATCH/DELETE`, включая refresh/logout; безопасные методы и Bearer-only запросы не проверяются. Cookie имеет `Secure` в staging/prod и без `Secure` только в dev. |
| Rate limiting | slowapi + общее Redis-хранилище счётчиков между API workers: 5 попыток логина / 15 мин с IP; экспорт — 10/час для клиента. |
| Валидация загрузок | magic-bytes (не доверять расширению), max 100МБ, антивирус-скан (ClamAV) — опц. |
| SQL-injection | только параметризованные запросы / ORM, никакого f-string SQL. |
| Secrets | `.env` (dev), Vault/AWS Secrets Manager (prod). |
| CORS | strict allowlist origin. |
| HTTPS | HSTS, TLS1.3 only. |
| Аудит | все mutation-действия менеджера → `audit_log`. |
| Логи без PII | не пишем пароли/токены в лог. |
| Бэкапы | nightly pgdump + WAL archiving; периодический restore-test. |
| Dependency scan | `pip-audit` / `npm audit` в CI. |
| SAST | `bandit`, `ruff`, `eslint`. |

---

## 12. Observability: логи, метрики, мониторинг

- **Логи:** `structlog` → JSON → Loki. Correlation ID на каждый запрос (middleware).
- **Метрики:** Prometheus (`prometheus-fastapi-instrumentator`). Дашборды: RPS, p95 latency, error rate, очереди Celery, длительность импорта.
- **Трейсинг:** OpenTelemetry → Tempo. Trace ID прокидывается в логи.
- **Алёрты (Alertmanager):**
  - error rate > 1% за 5 мин.
  - очередь Celery > 100 задач.
  - импорт FAILED.
  - рост 5xx.
- **Uptime:** внешние пробы `/healthz` (Uptime Kuma).

---

## 13. Тестирование

| Уровень | Инструмент | Покрытие |
|---|---|---|
| Unit (domain/services) | `pytest` | логика ценообразования, апсерт-стратегии, edge-cases. |
| Integration (API+БД) | `pytest` + testcontainers (Postgres/Redis/MinIO) | все эндпоинты, RBAC, импорт CSV. |
| Contract (OpenAPI) | `schemathesis` | fuzzing по спеке. |
| E2E (frontend) | `Playwright` | ключевые сценарии: логин клиента, фильтр, экспорт, оформление заявки, импорт менеджером. |
| Нагрузочное | `k6` | 100 RPS на каталог, импорт 50k строк. |
| Покрытие | `coverage` ≥ 80% для критичных модулей. |

**Фикстуры:** фабрики на `factory-boy`, реалистичный датасет 10k SKU.

---

## 14. Деплой и инфраструктура

### Среды
- `local` — docker-compose (БД, Redis, MinIO, ngrok для Telegram webhook).
- `staging` — зеркало прода, те же данные (анонимизированные).
- `prod`.

### Docker-compose (dev) — сервисы
- `db` (postgres:16), `redis`, `minio`, `api`, `worker`, `frontend`, `bot`, `nginx`.

### CI/CD (GitLab CI / GitHub Actions)
1. `lint` (ruff, eslint, prettier).
2. `test` (pytest, playwright — параллельно).
3. `security` (bandit, pip-audit, trivy image scan).
4. `build` (docker images → registry).
5. `migrate` (alembic upgrade head — на staging автоматически, на prod — с approve).
6. `deploy` (rolling update).

### Миграции
- Alembic, **всегда** reversible (up + down).
- Долгие миграции на больших таблицах — через `CREATE INDEX CONCURRENTLY`, batch.

### Бэкапы
- PostgreSQL: WAL-G → S3 (PITR). Retention 30 дней.
- MinIO: versioning + cross-region replication.

---

## 15. Roadmap разработки по этапам

> Оценки — грубые, для команды 1 BE + 1 FE + 0.3 DevOps. Параллельные потоки отмечены `‖`.

### Этап 0 — Подготовка (3–5 дней)
- Репозитории (monorepo: `apps/api`, `apps/web`, `infra`).
- Docker-compose, pre-commit (ruff, black, eslint, prettier).
- CI-скелет.
- OpenAPI-спека (черновик).

### Этап 1 — БД и ядро BE (5–7 дней)
- Модели, миграции Alembic.
- Базовый CRUD-слой (repositories).
- Конфиг (`pydantic-settings`), structlog, OpenTelemetry.

### Этап 2 — Авторизация и RBAC (4–5 дней)  ‖ Этап 1
- JWT (access+refresh), сессии, `/auth/*`.
- Middleware RBAC.
- Seed-аккаунт менеджера.

### Этап 3 — Каталог и цены (6–8 дней)
- `products`, `brands`, `series`, `user_brands`.
- `PricingService`, SQL с расчётом цены «на лету».
- Эндпоинты каталога + фильтры + пагинация.
- Кэш Redis с тегами.

### Этап 4 — Импорт CSV (Celery) (5–7 дней)  ‖ Этап 5
- Celery + Redis.
- Парсер polars, upsert, режимы импорта.
- Загрузка ZIP с фото → S3 → связывание.
- PriceListVersion, отчёты об ошибках.

### Этап 5 — Frontend: каркас и каталог (8–10 дней)  ‖ Этап 4
- Nuxt 3, дизайн-система (Tailwind, палитра, компоненты-плитки).
- Логин, лэйаут с sidebar, ЛК клиента.
- Страница каталога: плитка/таблица, фильтры, поиск, lightbox с зумом.
- Переключатель цен розница/скидка.

### Этап 6 — Заявки + уведомления (5–7 дней)
- Корзина на клиенте, оформление, снапшот цен.
- Лента заявок клиента и менеджера.
- SSE + Telegram Bot.
- Статусы.

### Этап 7 — Экспорт (3–5 дней)
- Генерация CSV/XLSX/PDF (Celery).
- Скачивание через presigned URL.
- Раздел «Файловый архив» (PDF-каталоги брендов).

### Этап 8 — Менеджер-панель: пользователи и матрица скидок (4–5 дней)
- CRUD клиентов, генерация паролей.
- Матрица скидок по брендам, аудит.
- Курсы валют.

### Этап 9 — Hardening и Edge-cases (3–5 дней)
- Soft-delete/архив при импорте.
- Rollback версии прайса.
- i18n (RU/EN).
- Rate limits, валидация файлов.

### Этап 10 — Observability и тесты (5 дней)
- Дашборды Grafana, алёрты.
- E2E Playwright, нагрузочное k6.

### Этап 11 — Деплой в prod (3–4 дня)
- Nginx/Caddy, TLS, бэкапы, runbook.

### Этап 12 (post-MVP) — Telegram Mini App (5–7 дней)
- `/m/**` subroute, Telegram-auth, mobile-оптимизированные экраны.

**Итого MVP:** ~6–8 недель при полноценной команде.

---

## 16. Принятые решения (Decisions Log)

> Согласовано с заказчиком 2026-08-11.

| # | Вопрос | Решение | Влияние на архитектуру |
|---|---|---|---|
| 1 | Базовая и display-валюты | **Базовая BYN.** Доп. для отображения: RUB / USD / EUR. Курс — **НБ РБ, ежедневное автообновление** | Scheduler (Celery beat) `fetch_nbrb_rates` ежедневно в 00:05. Эндпоинт НБ РБ: `https://www.nbrb.by/api/exrates/rates?periodicity=0`. См. §17. |
| 2 | Складской учёт | **Не нужен.** Только статус: `В наличии` / `Под заказ` | Упрощаем `stock_status` до 2 значений (плюс `АРХИВ` для soft-delete). |
| 3 | Срок жизни `override_price` | **⏳ Ждём финального подтверждения.** Рекомендация: авто-сброс при импорте + предупреждение в отчёте. | Логика в worker'е импорта + блок в отчёте ошибок. |
| 4 | Регистрация клиентов | **Только ручное создание менеджером** | Нет public `/register`. Эндпоинт `POST /manager/users` генерирует temp-пароль (показ 1 раз). |
| 5 | Канал уведомлений | **Только Telegram** (бот менеджеру + опц. клиенту). SMTP не нужен | Убираем SMTP-сервис из стека. Упрощаем §9. |
| 6 | Объём каталога | **Старт ≤ 1000 SKU, перспектива — десятки тысяч** | Архитектуру делаем сразу «с запасом»: пагинация, индексы GIN, кэш. Но на 1000 хватит и простого `LIMIT/OFFSET` — виртуальный скролл необязателен на старте. |
| 7 | История курсов / фиксация | **Клиент видит только текущий курс.** Три уровня фиксации: (а) **курс для прайса** — менеджер задаёт курс конвертации CSV→BYN при импорте (manual или «по НБ РБ на сегодня»); (б) **курс для клиента** — менеджер фиксирует display-курс конкретному клиенту по договору; (в) **снапшот в заказе** — при оформлении заявки курс замораживается навсегда. **Кнопка «Пересчитать по курсу НБ РБ»** в корзине/счете для пересчёта display-валюты по текущему курсу. | `price_list_version.rate_to_byn`, `users.fixed_rate_id`, `orders.exchange_rate` (snapshot). См. §17. |
| 7.1 | Уведомления об изменении цены | **Да.** После импорта — сводка менеджеру; клиентам (opt-in) — уведомление по товарам из их корзины/избранного/последних заказов | См. §20 «Центр уведомлений». |
| 8 | Брендирование | **Единый бренд** (без whitelabel по поддоменам) | Один набор лого/цветов. Упрощаем роутинг. |
| 9 | Язык интерфейса и каталога | **Только RU** | i18n оставляем как техническую возможность, но не включаем в MVP. Убираем Этап 8 (i18n) из критического пути. |
| 10 | Согласие / политика | **Да, требуется** | Чекбокс согласия при первом входе клиента; страница «Политика конфиденциальности»; лог согласия в `consent_log`. |
| 11 | Регион хостинга | **Беларусь** | Провайдеры: beCloud, *activeby*, datacenter.by. НБ РБ-курс доступен без Geo-ограничений. Учесть требования Закона РБ «О защите персональных данных» (локализация ПДн в РБ — выполняется автоматически). |
| 12 | Интеграция с 1С | **Оставить архитектурную возможность** (не реализовывать в MVP) | Спроектировать DTO заказов в формате, близком к 1С (XML/JSON CommerceML 2.x). Эндпоинт-заглушка `POST /integrations/1c/orders/export` под auth-token. См. §18. |
| 13 | Контейнеризация | **Да, Docker + docker-compose** (dev и prod). 8+ сервисов (API, Celery worker, Celery beat, Nuxt, PostgreSQL, Redis, MinIO, TG-бот, Nginx) — без compose не управляемо. Идентичные среды dev/staging/prod, лёгкий деплой на РБ-VPS, мгновенный rollback версиями образов | `docker-compose.yml` (dev) + `docker-compose.prod.yml` (override). Подробно см. §14. |
| 14 | Семантика rollback версии прайса | **Восстановление + архив новых; откатывать только последнюю DONE-версию** (согласовано 2026-08-16) | `POST /manager/prices/versions/{id}/rollback`: товарам, существовавшим до версии X, возвращаются `base_price`/`override_price` из их последнего снапшота `price_history` до X; товары, впервые появившиеся в X, архивируются (soft-delete, `stock_status=ARCHIVE`). Guards: версия существует (404), статус DONE, последняя DONE, не откачена ранее (иначе 409). Аудит: `price_list_versions.rolled_back_at/rolled_back_by` (§5); кэш каталога инвалидируется тегами импорта. |
| 15 | Схема хранения JWT-ключей RS256 | **PEM-файлы, смонтированные в контейнеры read-only** (согласовано 2026-08-16) | Dev: HS256 + `SECRET_KEY` (без изменений). Prod: `JWT_ALGORITHM=RS256`; RSA-2048 ключи генерируются на хосте (`make gen-jwt-keys`), лежат в `infra/jwt-keys/` (`.gitignore`), монтируются read-only, пути — `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`. Публичный ключ раздаётся сервисам, проверяющим токены. Vault не входит в MVP-инфраструктуру — §11 скорректирован с «vault» на эту схему. |
| 16 | Экспорт каталога: метод и форматы | **POST; CSV+XLSX сейчас, PDF отложен** (согласовано 2026-08-17) | Расхождение §6 (GET) и SITEMAP (POST) устранено в пользу POST — запуск генерации создаёт job (side-effect). Форматы: `csv` (UTF-8 BOM) и `xlsx` (openpyxl); `pdf` → 422 с сообщением (weasyprint требует системных deps — отдельной задачей, см. §16.1 F). Job-стейт — Redis (`export:job:{id}`, TTL 24 ч, статусы QUEUED/RUNNING/DONE/FAILED, доступ только владельцу); файлы — S3 `csv-exports/` (TTL 7 дней); rate-limit 10/час на клиента (§11). |

### §16.1 Дополнительные фичи (approved для MVP, согласовано 2026-08-11)

| ID | Фича | Кратко | Влияние |
|---|---|---|---|
| **A** | Избранное / список отслеживания | Клиент отмечает SKU звёздочкой | Таблица `favorites(user_id, product_id)` + страница `/favorites` + источник для `PRICE_CHANGED_DIGEST` |
| **B** | Массовое добавление в корзину по SKU | Вставка списка артикулов из Excel/textarea | Страница `/bulk-add`, парсинг `qty\tname...` или `sku=qty`, валидация, частичный успех |
| **C** | Повтор прошлого заказа в 1 клик | Кнопка «Повторить» в истории заявок | `POST /orders/{id}/repeat` → новый черновик |
| **D** | Сохранённые корзины / черновики | Корзина не теряется между сессиями | `carts` + `cart_items` (persist в БД, не только localStorage) |
| **E** | Комментарии к позициям заказа | «нужен сертификат», «доставка до 15-го» | `order_items.note`, `orders.note` |
| **F** | Экспорт заявки в PDF | Для бухгалтерии клиента, с реквизитами | Celery-генерация PDF (weasyprint), шаблон с реквизитами компании клиента |
| **G** | Дашборд менеджера | Топ-товары, топ-клиенты, динамика заявок, выручка | Отдельная страница `/manager`, агрегирующие SQL-запросы, кэш |
| **H** | 2FA (TOTP) для менеджера | Защита админки (Google Authenticator) | Поле `users.totp_secret`, flow при логине, recovery-коды |
| **I** | Журнал активных сессий + отзыв | Клиент/менеджер видит сессии и отзывает | Использовать таблицу `sessions` (§5), страница `/profile/sessions` |
| **J** | История цены по SKU (график) | Прозрачность для клиента | Таблица `price_history(product_id, price, changed_at)` — пишется при каждом импорте |

### ⏳ Ожидают подтверждения
- **п.3** — жизненный цикл `override_price`: авто-сброс (А) vs сохранение (Б). **Решено (Этап 4, 2026-08-12): вариант (Б) «сохранение».** При upsert `override_price` обновляется только если CSV содержит `discount_price`; иначе ранее заданное менеджером значение сохраняется (не разрушается импортом). Опция авто-сброса (А) оставлена как будущая настройка.

---

## 17. Модуль курсов валют НБ РБ (новое, по решению п.1 и п.7)

### 17.1. Автозагрузка курсов
- **Источник:** `https://www.nbrb.by/api/exrates/rates?periodicity=0` (ежедневные курсы).
- **Расписание:** Celery beat, `0 5 0 * * *` (каждый день в 00:05 по Европе/Минску).
- **Хранение:** таблица `exchange_rates` (история для аудита + снапшотов заказов).
- **Fallback:** если НБ РБ недоступен — берём последний успешный курс + алёрт менеджеру в Telegram.

### 17.2. Три уровня курса (fixed по договору п.7)

```
┌─────────────────────────────────────────────────────────────────┐
│  УРОВЕНЬ 1 — Курс прайса (при импорте CSV)                       │
│  Менеджер выбирает: «валюта CSV» + источник курса               │
│  (manual ввод значения | «по НБ РБ на сегодня»).                │
│  → base_price хранится ВСЕГДА в BYN (конвертация один раз).     │
│  → price_list_version.rate_to_byn, .rate_source, .base_currency │
│                                                                  │
│  MVP (Этап 4, 2026-08-12): реализован только MANUAL-источник    │
│  (rate_source='MANUAL'). Опция «по НБ РБ на сегодня» отложена   │
│  до реализации задачи fetch_nbrb_rates (наполнение exchange_rates).│
├─────────────────────────────────────────────────────────────────┤
│  УРОВЕНЬ 2 — Курс отображения клиента (display)                  │
│  display_currency ∈ {BYN, USD, EUR, RUB} (выбор клиента).        │
│  display_rate = COALESCE(                                        │
│      user.fixed_rate.rate,        -- фиксация по договору        │
│      current_nbrb_rate            -- иначе текущий НБ РБ         │
│  )                                                               │
├─────────────────────────────────────────────────────────────────┤
│  УРОВЕНЬ 3 — Снапшот курса в заказе                              │
│  При POST /orders пишем orders.exchange_rate + .currency_code.   │
│  Сумма заказа зафиксирована навсегда, не пересчитывается.        │
└─────────────────────────────────────────────────────────────────┘
```

### 17.3. Кнопка «Пересчитать по курсу НБ РБ»
- **Где:** в корзине, в черновике счёта, в деталях незавершённой заявки.
- **Что делает:** принудительно берёт display-суммы по **текущему** курсу НБ РБ (игнорируя фиксацию по договору) — превью «сколько будет по сегодняшнему курсу».
- **Важно:** это **только preview**, не меняет `user.fixed_rate` и не создаёт новый снапшот, пока клиент не нажмёт «Оформить заявку» (тогда снапшот берётся по тому курсу, который актуален на момент оформления).
- Реализация: фронтовый toggle `price_calc_mode = fixed | nbrb_current` → query-параметр в `/catalog`, `/pricing/calculate`, `/cart`.

### 17.4. Схема данных (дополнение к §5)
```sql
-- users (доп. поля)
ALTER TABLE users ADD COLUMN fixed_rate_id UUID REFERENCES exchange_rates(id);
ALTER TABLE users ADD COLUMN display_currency CHAR(3) DEFAULT 'BYN';

-- price_list_versions (доп. поля — курс прайса при импорте)
ALTER TABLE price_list_versions ADD COLUMN base_currency CHAR(3) DEFAULT 'BYN';
ALTER TABLE price_list_versions ADD COLUMN rate_to_byn  NUMERIC(12,4) DEFAULT 1;
ALTER TABLE price_list_versions ADD COLUMN rate_source  TEXT;  -- 'MANUAL' | 'NBRB_<date>'

-- exchange_rates
CREATE TABLE exchange_rates (
    id            UUID PRIMARY KEY,
    currency_code CHAR(3) NOT NULL,            -- USD, EUR, RUB
    rate          NUMERIC(12,4) NOT NULL,      -- за scale единиц к BYN
    scale         INT NOT NULL DEFAULT 1,      -- НБ РБ: для RUB scale=100
    fetched_at    DATE NOT NULL,               -- дата курса
    source        TEXT DEFAULT 'NBRB',
    is_manual     BOOLEAN DEFAULT FALSE,       -- true, если менеджер ввёл вручную
    UNIQUE (currency_code, fetched_at, source)
);
CREATE INDEX ix_rates_currency_date ON exchange_rates(currency_code, fetched_at DESC);

-- orders (снапшот)
ALTER TABLE orders ADD COLUMN exchange_rate  NUMERIC(12,4) NOT NULL;
ALTER TABLE orders ADD COLUMN currency_code  CHAR(3) NOT NULL DEFAULT 'BYN';
ALTER TABLE orders ADD COLUMN rate_source    TEXT;  -- 'FIXED' | 'NBRB_<date>'
```

### 17.5. UI менеджера — раздел «Курсы валют»
- Таблица последних курсов (источник, дата, значение).
- Кнопка «Обновить вручную» (форс-фетч НБ РБ).
- Форма «Зафиксировать курс клиенту»: выбор клиента + валюта + значение (manual) или «по текущему НБ РБ».
- При импорте CSV — выбор «Валюта прайса» + «Курс» (manual / по НБ РБ сегодня).

### 17.6. UI клиента
- В шапке/профиле — выбор display-валюты (BYN/USD/EUR/RUB).
- Бейдж «курс по договору 3.27 BYN/USD» если есть фиксация.
- В корзине — кнопка-переключатель «⚖️ По курсу НБ РБ» для preview-пересчёта.

---

## 18. Подготовка к интеграции с 1С (новое, по решению п.12)

> В MVP **не реализуется**, но архитектура готовится.

### 18.1. Принципы
- DTO заказов в формате **CommerceML 2.x** (де-факто стандарт обмена с 1С в СНГ) — XML или JSON-адаптация.
- Отдельный набор эндпоинтов под subroute `/api/integrations/1c/**`, авторизация по статическому token (header `X-Integration-Token`), IP-allowlist.
- Версионирование схемы обмена (`?schema_version=2.10`).

### 18.2. Эндпоинты-заглушки (возвращают 501 Not Implemented, но спроектированы)
| Method | Path | Назначение (будущее) |
|---|---|---|
| GET | `/api/integrations/1c/orders/export` | Выгрузка новых/изменённых заказов в 1С (последний `?since=`). |
| POST | `/api/integrations/1c/prices/import` | Приём прайса из 1С (вместо ручного CSV). |
| POST | `/api/integrations/1c/stock/import` | Обновление складских статусов из 1С. |
| POST | `/api/integrations/1c/orders/status` | Возврат статуса заказа из 1С (отгружен и т.д.). |

### 18.3. Подготовка в коде
- Слой DTO `app/schemas/commerceml/` с Pydantic-моделями по схеме CommerceML.
- Поле `orders.external_id` (для связи с номером документа в 1С).
- Поле `products.external_1c_guid` (для связи номенклатуры).
- `audit_log` фиксирует все exchange-операции.

---

## 19. Корректировки к Roadmap (по итогам решений)

Изменения относительно §15:

- **Этап 3 (Каталог и цены):** добавить сервис курсов валют + display-currency.
- **Новый Этап 3.5 — Курсы НБ РБ (2 дня):** scheduler Celery beat, загрузка, UI менеджера «Курсы», фиксация курса клиенту.
- **Этап 8 (i18n):** перенесён в post-MVP (решение п.9).
- **Этап 8 (бывш. матрица скидок) → Этап 8 «Пользователи + скидки + курсы»** — объединить.
- **Этап 9 (Hardening):** добавить чекбокс согласия на обработку ПДн + лог.
- **Новый Этап 11.5 — 1С-ready заглушки (1 день):** DTO + эндпоинты 501.
- **Деплой:** выбор РБ-провайдера (например, VPS на activeby/datacenter.by), домен в зоне `.by`.
- **Новый Этап 6.5 — Центр уведомлений + изменение цен (3–4 дня):** модуль из §20, в т.ч. уведомления об изменении цены после импорта.
- **Новые фичи A–J (см. §16.1):** распределить по этапам:
  - **A (избранное), C (повтор заказа), E (комментарии)** → Этап 6 (Заявки), +1 день.
  - **B (массовое добавление)** → Этап 6.6 (новый).
  - **D (persist-корзина в БД)** → перенесена в Этап 6: модели `Cart`/`CartItem` уже созданы в миграции `0001_initial_schema`, REST `/cart/items` реализуется в ядре Этапа 6 (расширение §15, где изначально предполагалась корзина только на клиенте). Этап 6.6 теперь = только фича B.
- **REST-контракты Этапа 6 (дополнение §6, ранее не детализированные):**
  - `/cart` (persist в БД, один на пользователя): `GET /cart`, `POST /cart/items`, `PUT /cart/items/{sku}`, `DELETE /cart/items/{sku}`, `DELETE /cart`.
  - `/favorites`: `GET /favorites`, `POST /favorites` (`{sku}`), `DELETE /favorites/{sku}`.
  - `/orders` (клиент): `GET /orders`, `POST /orders` (201, снапшот цен/курса), `GET /orders/{id}`, `POST /orders/{id}/repeat` (→ корзина), `POST /orders/{id}/cancel`.
  - `/manager/orders`: `GET /manager/orders` (фильтры client/status/manager), `GET /manager/orders/{id}`, `PATCH /manager/orders/{id}` (status и/или manager_id + запись в `audit_log`).
  - Статус-коды: `200` (списки/детали), `201` (создание заказа), `204` (удаление), `400` (невалидный/архивный SKU), `404` (не найдено / чужой заказ для клиента), `409` (запрещённый FSM-переход).
  - **F (PDF-заявка)** → Этап 7 (Экспорт), +1 день.
  - **G (дашборд)** → Этап 8 (Менеджер-панель), +2 дня.
  - **H (2FA), I (сессии)** → Этап 9 (Hardening), +2 дня.
  - **J (история цены)** → Этап 4 (Импорт), +1 день (запись `price_history` при импорте).
- **Docker (решение п.13):** `docker-compose.yml` поднимается уже на Этапе 0.

---

## 20. Центр уведомлений (Notification Hub)

> Единый модуль для всех типов уведомлений. Каналы: **Telegram** (основной), **in-app** (колокольчик в шапке + SSE-pull), **email** — опционально, не в MVP.

### 20.1. Архитектура
```
[Триггер: импорт / заказ / статус / курс / цена]
        │
        ▼
[NotificationDispatcher (сервис)]
        │
        ├──▶ TelegramBot.send()            (синхронно, с retry)
        ├──▶ DB: notifications (in-app)    (для SSE / колокольчика)
        └──▶ [future] EmailService
```
Шаблоны сообщений — Jinja2, хранятся в `templates/notifications/*.j2`. Локализация RU.

### 20.2. Таблица `notifications` (in-app)
```sql
CREATE TABLE notifications (
    id          UUID PRIMARY KEY,
    user_id     UUID REFERENCES users(id),   -- получатель (NULL = всем менеджерам)
    type        TEXT NOT NULL,               -- PRICE_CHANGED / NEW_ORDER / ...
    title       TEXT,
    body        TEXT,
    payload     JSONB,                        -- контекст (sku, order_id, diff...)
    channel     TEXT[],                       -- {'telegram','inapp'}
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_notif_user_unread ON notifications(user_id) WHERE is_read = FALSE;
```

### 20.3. Реестр типов уведомлений
| type | Получатель | Триггер | Канал | Текст (пример) |
|---|---|---|---|---|
| `NEW_ORDER` | Менеджер | `POST /orders` клиентом | TG + in-app | «🆕 Заявка #1024 от ООО "Рога", 18 поз., 4 320 BYN» |
| `ORDER_STATUS_CHANGED` | Клиент | смена статуса менеджером | in-app (+TG опц.) | «✅ Заявка #1024 отгружена» |
| `PRICE_CHANGED` | Менеджер | после импорта CSV | TG + in-app | «📈 Прайс обновлён: 80↑, 40↓, 12 новых, 5 сброшена фикс-цена» |
| `PRICE_CHANGED_DIGEST` | Клиент (opt-in) | после импорта, по товарам из корзины/избранного | in-app + TG | «⚠ Изменились цены на 6 товаров в вашей корзине» |
| `STOCK_CHANGED` | Клиент (opt-in) | «Под заказ»→«В наличии» по товарам избранного | in-app | «✅ Товар A-100 снова в наличии» |
| `IMPORT_FAILED` | Менеджер | ошибка Celery-таски | TG | «❌ Импорт не удался: неверный формат строки 142» |
| `RATE_FETCH_FAILED` | Менеджер | НБ РБ недоступен | TG | «⚠ Не удалось получить курс НБ РБ, использую последний от 2026-08-10» |
| `ACCOUNT_CREATED` | Клиент | менеджер создал аккаунт | показ при первом входе + TG (если есть username) | «🔑 Доступ создан. Логин: ..., временный пароль: ...» |

### 20.4. Уведомление об изменении цены (детально)
**После импорта CSV** worker:
1. Сравнивает новые `base_price` / `override_price` с предыдущей версией.
2. Считает агрегаты: `count_up`, `count_down`, `count_new`, `count_override_reset` (по п.3), `count_unchanged`.
3. **Менеджеру (всегда):** сводное Telegram-сообщение + in-app со ссылкой на детальный отчёт (таблица с колонкой Δ%).
4. **Клиентам (opt-in):** для каждого клиента проверяем его корзину (`cart_items`), избранное (`favorites`), последние N заказов. Если среди изменённых SKU есть совпадение → формируем дайджест «⚠ Изменились цены на K товаров в вашей корзине/избранном».

**Настройки уведомлений** (профиль клиента + профиль менеджера):
- чекбоксы включения/выключения по каждому `type`;
- выбор канала (in-app / Telegram / оба);
- для `PRICE_CHANGED_DIGEST` — выбор источника отслеживания: корзина, избранное, последние заказы.

### 20.5. UI
- **Колокольчик** в шапке (клиент + менеджер) с бейджем непрочитанных.
- Dropdown со списком + кнопка «Отметить все прочитанными».
- Страница `/notifications` — полный список с фильтром по типу.
- SSE `/api/v1/notifications/stream` — push в реальном времени.
- Профиль → раздел «Уведомления» — настройки каналов и типов.

---

> **Следующий шаг:** подтвердить п.3 (рекомендация А — авто-сброс `override_price`), после чего зафиксировать OpenAPI-спеку, карту сайта (`SITEMAP.md`) и начать Этап 0.

---

## 21. Управление изменениями (Change Management)

> Раскрытие принципа из баннера в начале документа.

### 21.1. Каноничные источники
1. `ARCHITECTURE_PLAN.md` (этот файл) — архитектура, БД, API, логика, решения.
2. `SITEMAP.md` — карта экранов, роутинг, состав страниц, навигация.
3. `openapi.yaml` (будет сгенерирован) — контракт API уровня схемы.

### 21.2. Когда требуется обновить документ
Обязательно обновлять, если в коде появляется (или планируется):
- новая/изменённая таблица БД или поле;
- новый/изменённый REST-эндпоинт или его контракт;
- отклонение от выбранного стека или архитектурного паттерна;
- новая бизнес-логика, edge-case, правило расчёта;
- новая роль, экран, поток пользователя;
- изменение внешней интеграции (Telegram, НБ РБ, 1С).

### 21.3. Процедура изменения
1. Открыть соответствующий раздел (`§5` БД / `§6` API / `§15` Roadmap / `§16` Decisions Log / `SITEMAP.md`).
2. Внести правку.
3. Добавить строку в `§16` (Decisions Log): `| NN | <что> | <решение> | <влияние> |`.
4. Поднять минорную версию документа (v1.1 → v1.2), указать дату.
5. Если правка ломает совместимость — отметить в `CHANGELOG` и продумать миграцию.

### 21.4. Промпт для ИИ-ассистента (вставлять в начало каждой сессии)
> «Перед началом работы прочитай `ARCHITECTURE_PLAN.md` и `SITEMAP.md` целиком. Это каноничная спека. Реализуй только то, что описано. Если для задачи нужен элемент, которого нет в спеке, или существующий элемент нужно изменить — **сначала** обнови документ (новая строка в §16 Decisions Log + правка в нужном разделе + bump версии), **потом** пиши код. Не додумывай молча. Если есть неоднозначность — задай вопрос.»

### 21.5. Шаблон строки Decisions Log
```
| NN | <тема> | <РЕШЕНИЕ> | <влияние на архитектуру/ссылка на §> |
```

---

> **Текущая версия документа:** v1.4
> **Сопутствующие файлы:** `SITEMAP.md` (карта сайта/экранов).
