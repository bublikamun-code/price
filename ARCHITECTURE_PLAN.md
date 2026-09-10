# 🏗️ B2B «Клиентский портал с динамическими прайс-листами»
## Архитектурный документ и Roadmap разработки

> **Роль документа:** Мастер-план (Technical Design Document + RFC), на основе которого ведётся пошаговая реализация. Документ расширяет исходное ТЗ и закрывает пробелы (security, edge-cases, observability, deploy).
>
> **Статус:** v1.9 — готов к передаче команде / ИИ-ассистенту.
> **Дата:** 2026-08-26

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

### Liquid Glass — двухуровневое стекло (2026-09-05; действует)
> Реализация в `apps/web/assets/css/main.css` (токены `--glass-*`, `--ambient-*`) и
> `tailwind.config.ts` (`glass`, `glass-border`, стеклянные `shadow-card`). Палитра
> не менялась — материал берётся из `--color-surface` с альфой.

- **Уровень 1 — `.glass` («живое» стекло):** `backdrop-filter: blur(20px) saturate(1.6)`
  + полупрозрачный фон (`--glass-a-strong`). Только плавающие элементы, под которыми
  прокручивается контент: шапка (AppHeader), нижняя навигация (AppBottomNav, miniapp),
  попап корзины, тосты, дропдауны (BaseSelect), sticky-пагинация каталога, панели поиска.
  Fallback `@supports not (backdrop-filter)` → плотный фон.
- **Уровень 2 — `.card` («статичное» стекло):** полупрозрачный фон (`--glass-a`) +
  световая кромка (блики в `shadow-card`: верх `--glass-spec-top`, кольцо
  `--glass-spec-ring`, низ `--glass-spec-bot`), **без** backdrop-filter — нулевая
  цена для GPU на сетках каталога. Выход в плотный вид — утилита `.card-solid`.
- **Ambient-фон:** `body::before` — 3 фиксированных радиальных пятна (`--ambient-1..3`,
  альфа `--ambient-a`: ~0.10 light / ~0.22 dark), на которых стекло «читается».
- **Плотными остаются:** `.btn-primary`, активный `.nav-link-active` (с тонким верхним
  бликом), AppFooter. Оверлеи модалок — `bg-black/50 backdrop-blur-sm`.
- Тёмная тема: те же классы, значения альф и бликов — в `.dark`-переопределениях токенов.

### Эксперимент «Corporate Blue» (2026-09-08) — ОТКЛОНЁН пользователем 2026-09-09
> Плоская slate-палитра с синим акцентом (#2563EB light / #3B82F6 dark, радиусы
> 12/10px) была реализована через токены и отклонена пользователем по цвету.
> Канон остаётся Liquid Glass (выше). Ценность эксперимента: подтверждено, что
> смена палитры через токены (`main.css` + `tailwind.config.ts`) меняет дизайн
> всех ролей синхронно; воспроизведение — 30 минут (сценарий в design-lab).

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
| POST | `/api/v1/auth/login` | Вход (email+password). Возвращает access JWT (15 мин) + refresh в httpOnly cookie (7 дней). Если включена 2FA — без токенов: `{"two_fa_required": true, "ticket"}` (§16 п.22). |
| POST | `/api/v1/auth/refresh` | Обновить access. |
| POST | `/api/v1/auth/logout` | Отзыв refresh. |
| GET | `/api/v1/auth/me` | Текущий пользователь + матрица скидок. |
| PATCH | `/api/v1/auth/me` | Обновить свой профиль (partial update): `display_currency`, `price_digest_enabled`, `price_digest_sources` (§20.4), `consent_accepted: true` — принятие согласия (SITEMAP `/consent`): ставит `consent_accepted_at` и пишет `consent_log` (§16 п.20). |
| POST | `/api/v1/auth/2fa/setup` | (MANAGER) Сгенерировать TOTP-секрет + QR — без сохранения (§16 п.22). |
| POST | `/api/v1/auth/2fa/enable` | (MANAGER) Включить 2FA: `{secret, code}` → recovery-коды (показ 1 раз). |
| POST | `/api/v1/auth/2fa/verify` | Второй шаг логина при 2FA: `{ticket, code}` (TOTP или recovery) → токены+куки. |
| POST | `/api/v1/auth/2fa/disable` | (MANAGER) Отключить 2FA: `{code}` или `{password}`. |
| GET | `/api/v1/auth/sessions` | Свои активные сессии (фича I; `current` — по refresh-куке). |
| DELETE | `/api/v1/auth/sessions/{id}` | Отзыв своей сессии (текущая — с очисткой кук). |
| DELETE | `/api/v1/auth/sessions` | Отзыв всех своих сессий кроме текущей. |

### Каталог и ценообразование
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/catalog/products` | Список с пагинацией/фильтрами. Query: `q`, `brand[]`, `series[]`, `stock`, `price_mode=retail\|discount`, `page`, `per_page`, `sort`. Цены рассчитываются на лету под текущего клиента. |
| GET | `/api/v1/catalog/products/{sku}` | Детализация товара + соседи по серии. |
| GET | `/api/v1/catalog/filters` | Доступные фильтры (бренды, серии, статусы) — используется для UI. |
| GET | `/api/v1/catalog/pricing/calculate` | Расчёт цены под клиента (для корзины). Body: `[{sku, qty}]` → `[{sku, unit_price, total}]`. |
| POST | `/api/v1/catalog/resolve-bulk` | Проверка списка артикулов для массового добавления (фича B, SITEMAP `/bulk-add`): `{items: [{sku, qty?}]}` (≤500) → по строке: найден/нет, наименование, цена клиента, складской статус, ошибка. Ничего не добавляет (§16 п.20). |
| POST | `/api/v1/catalog/export` | Запуск генерации выгрузки каталога (метод приведён к POST — см. §16 п.16). Query: фильтры каталога (`q`, `brand_ids`, `series_ids`, `stock`, `price_calc_mode`) + `format=csv\|xlsx\|pdf` (PDF — weasyprint, §16 п.25). Rate-limit: 10/час на клиента. Возвращает `{job_id}`. |
| GET | `/api/v1/catalog/export/{job_id}` | Статус генерации (`QUEUED/RUNNING/DONE/FAILED`, только владелец job) + presigned URL (5 мин) готового файла из S3 `csv-exports/`. |

### Заявки (клиент)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/orders` | Мои заявки. |
| POST | `/api/v1/orders` | Создать заявку. Body: `items:[{sku,qty}]`, `notes`. Сервер пересчитывает цены, делает snapshot, фиксирует. |
| GET | `/api/v1/orders/{id}` | Детали. |
| POST | `/api/v1/orders/{id}/pdf` | Генерация PDF-выгрузки заявки для бухгалтерии (фича F, §16 п.25): 202 `{job_id}`, job-паттерн п.16; доступ: владелец-клиент или любой MANAGER. Rate-limit 10/час. |
| GET | `/api/v1/orders/export/{job_id}` | Статус job + presigned URL (5 мин) PDF из S3 `csv-exports/` (только владелец job). |
| GET | `/api/v1/dashboard` | Клиентская аналитика «Моя аналитика» (SITEMAP `/dashboard`): данные текущего пользователя — KPI по заявкам (без CANCELLED), заявки по дням за 30 дней, статусы, топ-5 товаров, последние/активные заявки, изменения цен в избранном, новинки, быстрые действия. Кэш Redis TTL 60 с (§16 п.20). |

### Менеджер (RBAC: `role=MANAGER`)
| Method | Path | Описание |
|---|---|---|
| POST | `/api/v1/manager/users` | Создать клиента (email, ФИО, компания, телефон, опц. `discount_percent_all`). Система генерирует temp-пароль и показывает 1 раз (§16 п.19). |
| GET | `/api/v1/manager/users` | Список клиентов: поиск `q` (email/ФИО/компания), стандартная пагинация §6; агрегаты `avg_discount_percent`, `orders_count`, `fixed_rate_currency` (§16 п.19). |
| GET \| PATCH \| `/api/v1/manager/users/{id}` | Профиль клиента (+ текущая матрица скидок и зафиксированный курс). PATCH: `full_name`, `company`, `phone`, `is_active`, `display_currency`. |
| POST | `/api/v1/manager/users/{id}/reset-password` | Сброс пароля: новый temp-пароль (показ 1 раз), все refresh-сессии отзываются (§16 п.19). |
| PUT | `/api/v1/manager/users/{id}/discounts` | Сохранить матрицу скидок `[{brand_id, percent}]` (полная замена). |
| PUT | `/api/v1/manager/users/{id}/fixed-rate` | Зафиксировать display-курс клиенту (§16 п.7б): `{currency_code, rate?}` — `rate` опущен → копия текущего курса НБ РБ; `{reset: true}` — снять фиксацию (§16 п.19). |
| POST | `/api/v1/manager/prices/import` | Загрузить CSV. Multipart. Body: `file`, `mode`, `currency`. Возвращает `version_id`. |
| GET | `/api/v1/manager/prices/versions` | История импортов + статус. |
| POST | `/api/v1/manager/prices/versions/{id}/rollback` | Откат версии (§16 п.14): товарам, существовавшим до версии, возвращаются цены из последнего снапшота `price_history` до неё; товары, впервые появившиеся в версии, архивируются (soft-delete, `ARCHIVE`). Разрешён только для последней DONE-версии; повторный откат/не-DONE/не последняя → 409. Инвалидирует кэш каталога тегами импорта. Возвращает карточку версии + счётчики `restored`/`archived`. |
| POST | `/api/v1/manager/prices/photo-zip` | Загрузить ZIP с фото серий (multipart, §10/§16 п.17): валидация (zip, magic-bytes, лимиты) → S3 tmp-uploads → Celery-обработка (webp thumb/large + матчинг к сериям). Возвращает `{job_id}` (202). |
| GET | `/api/v1/manager/prices/photo-zip/{job_id}` | Статус обработки ZIP (только владелец): `QUEUED/RUNNING/DONE/FAILED` + счётчики `files/matched/unmatched` и список ошибок. |
| GET \| PATCH | `/api/v1/manager/orders` | Все заявки, смена статусов. |
| POST | `/api/v1/manager/files` | Загрузить файл (PDF/CSV/ZIP). |
| GET | `/api/v1/manager/files` | Список. |
| DELETE | `/api/v1/manager/files/{id}` | Удалить. |
| POST | `/api/v1/manager/currencies/rate` | Установить курс валюты вручную (source=MANUAL): `{currency_code, rate, fetched_at?}` (§16 п.19). |
| GET | `/api/v1/manager/currencies/rates` | Курсы USD/EUR/RUB за последние 7 дней (все источники), для страницы «Курсы валют» (§16 п.19). |
| POST | `/api/v1/manager/currencies/refresh` | Форс-запрос курсов НБ РБ (постановка Celery-таски `fetch_nbrb_rates`), 202 (§16 п.19). |
| GET | `/api/v1/manager/dashboard` | Дашборд (фича G, §16 п.20): KPI (заявок сегодня/за 7 дней, выручка за месяц, новых клиентов за 7 дней, активные импорты), заявки по дням за 30 дней, топ-5 товаров и топ-5 клиентов по выручке за месяц, последние 5 заявок. Кэш Redis TTL 60 с. |
| GET | `/api/v1/manager/products` | Каталог для управления (SITEMAP `/manager/catalog`): как `/catalog/products` + колонки `base_price`, `override_price`, `stock_status`, бренд, серия; фильтры `q`, `brand_id`, `stock`, пагинация (§16 п.20). |
| POST | `/api/v1/manager/products/export` | Полный экспорт продукции в CSV (202 `{job_id}`): все характеристики колонками (объединение ключей `attributes`, sorted; вложенные значения — JSON) + ссылки на фото отдельными колонками «Фото N» (личное фото, иначе фото серии; публичный `/public/photo`, т.к. presigned TTL 5 мин непригоден для CSV). Колонки: артикул, наименование, бренд, серия, статус, остаток, цена розничная, цена договорная + характеристики + фото. Без персональных цен (выгрузка менеджера, ARCHIVED включены, удалённые — нет). Job-паттерн п.16 (тот же Redis-неймспейс `export:job:{id}`); rate-limit 10/час. |
| GET | `/api/v1/manager/products/export/{job_id}` | Статус job экспорта продукции (только владелец) + presigned URL (5 мин) из S3 `csv-exports/`. |
| PATCH | `/api/v1/manager/products/{id}` | Ручное редактирование товара (§16 п.20): `override_price` (число ≥0 или null — сброс) и/или `stock_status`. Аудит `product.update`, инвалидация кэша каталога. |
| GET \| POST | `/api/v1/manager/brands` | Список брендов (с числом серий и товаров) / создать `{name}` — slug генерируется автоматически (§16 п.20). |
| PATCH \| DELETE | `/api/v1/manager/brands/{id}` | Переименовать `{name}` / удалить — 409, если есть серии или товары (§16 п.20). |
| GET \| POST | `/api/v1/manager/series` | Список серий (фильтр `brand_id`) / создать `{brand_id, name}`. |
| PATCH \| DELETE | `/api/v1/manager/series/{id}` | Переименовать / удалить — 409, если есть товары. |
| POST | `/api/v1/manager/series/{id}/photo` | Замена фото серии: multipart JPG/PNG/WebP ≤10 МБ → `photos-series/{slug}.webp` + `_thumb.webp` (конвенция §16 п.17), обновляет `series.photo_key`. |
| GET | `/api/v1/manager/audit` | Журнал аудита с фильтрами (`action`, `actor_id`, `target_type`), стандартная пагинация §6. |

### Файлы (общедоступные/авторизованные)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/files` | Список downloadable assets (PDF-каталоги брендов, выгрузки CSV). Фильтр по типу/бренду. |
| GET | `/api/v1/files/{id}/download` | Presigned URL (время жизни — 5 мин). |
| GET | `/api/v1/files/photo` | Фото серии: `?key=photos-series/...` → 307-редирект на presigned URL (5 мин, §16 п.17). |

### Уведомления (in-app, pull)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/notifications` | Лента уведомлений текущего пользователя: фильтры `type`, `unread_only`, стандартная пагинация §6; в `meta` — `unread_count` (колокольчик). Pull-модель (§16 п.20). |
| PATCH | `/api/v1/notifications/{id}/read` | Пометить прочитанным (только своё, иначе 404). |
| PATCH | `/api/v1/notifications/read-all` | Пометить все свои прочитанными → 204. |
| GET | `/api/v1/notifications/stream` | SSE-stream новых уведомлений в реальном времени (§16 п.26). Авторизация по cookie `access_token` (EventSource не умеет заголовки; query-токен исключён — попадает в логи). Событие: `notification` c JSON уведомления; heartbeat-комментарий каждые 20 с. Pull-эндпоинты остаются fallback'ом. |

### Корзина (клиент, persist в БД — §19)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/cart` | Корзина с позициями и расчётом. |
| POST | `/api/v1/cart/items` | Добавить `{sku, qty}`. |
| PUT | `/api/v1/cart/items/{sku}` | Изменить количество. |
| DELETE | `/api/v1/cart/items/{sku}` | Удалить позицию. |
| DELETE | `/api/v1/cart` | Очистить корзину. |
| POST | `/api/v1/cart/items/bulk` | Массовое добавление (фича B, §16 п.20): `{items: [{sku, qty}]}` (≤500) → `added` + `rejected` с причиной (не найден/архив/нет в наличии); частичный успех. |

### Публичная витрина (SEO, §16 п.29; без цен/остатков/ПДн)
| Method | Path | Описание |
|---|---|---|
| GET | `/api/v1/public/brands` | Список брендов, имеющих неархивные товары: `{data: [{id, name, slug}]}`. Без авторизации; кэш тегом `catalog`; rate-limit 60/мин IP. |
| GET | `/api/v1/public/brands/{slug}` | Бренд + серии (неархивные, только опубликованные с фото): `{data: {id, name, slug, series: [{id, name, slug, photo_thumb}]}}`; 404 если бренд отсутствует/пуст. |
| GET | `/api/v1/public/series/{slug}/products` | Товары серии (неархивные): `{data: [{sku, name, photo}]}` — photo: личное фото товара (ключ `photos-product/…`; добавлено 2026-09-08 для витрины лендинга, без цен/остатков); пагинация §6 (`page`, `page_size`). |
| POST | `/api/v1/public/lead` | Лид-форма лендинга (добавлено 2026-09-10): `{company, contact_name, phone, email?, comment?, website(honeypot)}` → `201 {ok}`. Без авторизации и CSRF (анонимный); rate-limit 5/10мин на IP; создаёт `LEAD_CREATED`-уведомление всем менеджерам (in-app + telegram, §20). ПДн минимальны и передаются менеджеру по его же договорной роли. |
| GET | `/api/v1/public/photo?key=` | Thumb-фото серии для витрины: валидация ключа (префикс `photos-series/` + суффикс `_thumb.webp`, иначе 404) → 307 на presigned (5 мин). Без авторизации. |

### Telegram Mini App
| Method | Path | Описание |
|---|---|---|
| POST | `/api/m/v1/auth/telegram` | Авторизация по `initData` (HMAC-SHA256 подпись Telegram WebApp, §16 п.27): `{init_data, link_code?}` → при связанном `users.telegram_id` — токены+сессия как при логине; без связи, но с валидным `link_code` — линк + токены; иначе 401 `{link_required: true}`. auth_date старше 24 ч → 401. Rate-limit 5/15 мин; CSRF-exempt (логика §16 п.21). Только CLIENT. |
| POST | `/api/v1/auth/telegram/link-code` | (клиент, веб-кабинет) Выдать одноразовый код связки Telegram: `{code, expires_in: 600}` (Redis, TTL 10 мин, §16 п.27). |
| Прочие данные | | m-app использует существующие `/api/v1/**` эндпоинты с Bearer (каталог, корзина, заявки, уведомления) — отдельные `/m/v1`-копии не создаются (§16 п.27). |

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
- На вход: ZIP с файлами `serie_a.jpg`, `serie_b.jpg`... (JPG/PNG/WebP; лимиты — §16 п.17).
- Загрузка: `POST /manager/prices/photo-zip` (dropzone «обработать ZIP с фото серий» на странице импорта, SITEMAP §7); обработка — Celery-задача.
- Worker распаковывает, для каждого файла:
  - генерирует thumbnail (400×400 webp, fit — без кропа) и large (1200×1200 webp, fit);
  - кладёт в S3: `photos-series/{slug}.webp` (large) и `photos-series/{slug}_thumb.webp` (конвенция суффикса `_thumb`, §16 п.17);
  - связывает с `series.photo_key` = ключ large. Матчинг: нормализованное имя файла (без расширения, `_`/пробел → `-`, lower) == slug серии; приоритет — совпадение с именем из `series_photo` CSV, затем с slug по `series.name`.
- Выдача: `GET /api/v1/files/photo?key=` → 307 на presigned (5 мин); значения `photo_key`, не являющиеся http(s)-URL, трактуются как S3-ключи.
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
| CSRF | Для cookie-based auth — `SameSite=Lax` + double-submit: отдельная JS-readable cookie `csrf_token` и заголовок `X-CSRF-Token` должны совпадать (constant-time) на `POST/PUT/PATCH/DELETE`, включая refresh/logout, но кроме `/auth/login` (§16 п.21); безопасные методы и Bearer-only запросы не проверяются. Cookie имеет `Secure` в staging/prod и без `Secure` только в dev. |
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

- **Логи:** `structlog` → JSON → stdout (docker logs). Агрегация в Loki — Этап 11 (§16 п.23). Correlation ID на каждый запрос (middleware).
- **Метрики:** Prometheus (`prometheus-fastapi-instrumentator`). Дашборды: RPS, p95 latency, error rate, очереди Celery, длительность импорта.
- **Трейсинг:** OpenTelemetry → Tempo — Этап 11 (§16 п.23). Trace ID прокидывается в логи.
- **Алёрты (Alertmanager):**
  - error rate > 1% за 5 мин.
  - очередь Celery > 100 задач.
  - импорт FAILED.
  - рост 5xx.
- **Uptime:** внешние пробы `/healthz` (Uptime Kuma) — Этап 11 (§16 п.23).

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
- PostgreSQL: WAL-G → S3 (PITR). Retention 30 дней. (MVP Этапа 11: nightly `pg_dump -Fc` + retention 30 д. и restore-test по RUNBOOK; WAL-G/PITR — пост-MVP, §16 п.24.)
- MinIO: versioning + cross-region replication (пост-MVP, §16 п.24).

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
| 17 | Photo-ZIP: эндпоинты, конвенции ключей и матчинг | **Согласовано 2026-08-17** | Эндпоинты: `POST /manager/prices/photo-zip` (202 + job) и `GET .../photo-zip/{job_id}` (статус, владелец-only) — job-стейт в Redis по паттерну экспорта (§16 п.16); выдача фото — `GET /files/photo?key=` → 307 на presigned (5 мин). Ключи: large `photos-series/{slug}.webp` (1200×1200 fit), thumb `photos-series/{slug}_thumb.webp` (400×400 fit), суффикс `_thumb` — конвенция. Матчинг к серии: нормализованный stem файла == series.slug; приоритет — имя, заявленное в CSV `series_photo` (при импорте сохраняется в series.photo_key до появления webp). Лимиты: ZIP ≤100 МБ, распакованный объём ≤500 МБ, ≤2000 файлов, входные форматы JPG/PNG/WebP. Импорт CSV: `series_photo` → `series.photo_key` (§7, закрывает нереализованное ранее связывание). |
| 18 | Файловый архив: детали контракта | **Согласовано 2026-08-17** | `GET /files` — только авторизованные: CLIENT видит `visibility IN (PUBLIC, AUTHED)`, MANAGER — все записи; фильтры `type`, `brand_id`, стандартная пагинация §6. `GET /files/{id}/download` → `{"data": {"url", "expires_in": 300}}` (presigned, TTL 5 мин; 404 при отсутствии/недоступности по visibility). `POST /manager/files`: multipart `file` + Form: `type` (BRAND_PDF/CUSTOM_CSV/OTHER; PHOTO_ZIP — системный → 422), `visibility` (default AUTHED), `brand_id` (опц.); валидация: расширение .pdf/.csv/.zip + content-type + magic-bytes (%PDF/PK), лимит 200 МБ (`FILES_MAX_MB`), стриминг в S3 без буферизации (паттерн CSV-импорта); статусы 201/415/413/502. Хранение: бакет `pdf-catalogs` (§10), ключ `{type}/{uuid}{ext}`, `filename_display` — оригинальное имя. `GET /manager/files` — все записи, те же фильтры; `DELETE /manager/files/{id}` → 204 (сначала объект S3, затем запись БД). Страницы `/files` и `/manager/files` — по SITEMAP. |
| 19 | Этап 8 «Менеджер-панель: клиенты и курсы»: детализация контрактов | **Согласовано 2026-08-20** | Дополнен §6 (расхождения §6 ↔ SITEMAP устранены в пользу SITEMAP): `GET /manager/users` (список с поиском `q` и агрегатами avg-скидки/заказов), `PUT /manager/users/{id}/fixed-rate` (фиксация display-курса: `{currency_code, rate?}` manual-строкой source=MANUAL либо копией курса НБ РБ; `{reset: true}` — снять), `GET /manager/currencies/rates` (7 дней), `POST /manager/currencies/refresh` (202, Celery). Temp-пароль: `secrets.token_urlsafe(12)`, показ ровно 1 раз в теле ответа `POST /manager/users` и `POST .../reset-password` (в БД — только хэш); сброс пароля отзывает все refresh-сессии пользователя. In-app уведомление `ACCOUNT_CREATED` создаётся **без** plaintext-пароля (пароль передаётся клиенту вне системы). Все мутации пишут `audit_log` (`user.create`, `user.update`, `user.reset_password`, `user.discount.update`, `user.fixed_rate.set/reset`, `currency.rate.manual`); смена скидок/display-валюты/фикс-курса инвалидирует тег кэша `user:{id}` (§7.2). Матрица скидок — полная замена (`PUT`), `updated_by` = менеджер. |
| 20 | Дозакрытие экранов MVP: дашборд, manager-каталог/бренды, уведомления, bulk-add, consent | **Согласовано 2026-08-20** | Закрывает «мёртвые» пункты навигации (SITEMAP ↔ код). (1) **Дашборд (фича G)**: `GET /manager/dashboard`, кэш Redis TTL 60 с; выручка = Σ `order_items.unit_price×qty` заказов месяца без `CANCELLED`; «активные импорты» = версии в QUEUED/PROCESSING. (2) **Manager-каталог**: `GET /manager/products` (как каталог + base/override/статус), `PATCH /manager/products/{id}` (`override_price` или null-сброс, `stock_status`) с аудитом `product.update` и инвалидацией `catalog`+`filters`. (3) **Бренды/серии**: CRUD с guard 409 на удаление при наличии дочерних; slug генерируется из имени (нормализация §16 п.17), переименование slug не меняет (стабильные ключи фото); фото серии — `POST /manager/series/{id}/photo` (webp large+thumb по конвенции п.17). (4) **Уведомления**: pull-модель — `GET /notifications` (фильтры, `meta.unread_count`), `PATCH .../{id}/read`, `PATCH .../read-all`; **SSE-stream отложен** (колокольчик на pull + счётчике). (5) **Bulk-add (фича B)**: разбор текста (`SKU`, `SKU=qty`, `SKU\tqty`) — на клиенте; API: `POST /catalog/resolve-bulk` (проверка, ≤500 строк) + `POST /cart/items/bulk` (частичный успех, причины отказов). (6) **Consent (п.10)**: `PATCH /auth/me {consent_accepted: true}` → `consent_accepted_at` + запись `consent_log` (policy_version, ip, user-agent); `/consent` middleware-редирект после логина при NULL. |
| 21 | CSRF: стейл-куки и логин | **Согласовано 2026-08-20** | Фикс edge-кейса «403 на `/auth/login`, если в браузере остаточные `access_token`/`refresh_token`, а `csrf_token`-кука потеряна» (GUI-тест 2026-08-20, README «известный edge»). Решение: (1) `POST /auth/login` освобождён от CSRF-валидации — login-CSRF вне модели double-submit: запрос неаутентифицирован, креды передаются явно в теле, а не через ambient-куки; (2) при неуспешном логине (401) ответ чистит остаточные куки `access_token`/`refresh_token`/`csrf_token` (delete_cookie) — состояние браузера сходится; при успешном логине `_set_auth_cookies` перезаписывает все три (без изменений). Refresh/logout сохраняют CSRF-проверку (§11). |
| 22 | 2FA (фича H) и журнал сессий (фича I) — детализация контрактов | **Согласовано 2026-08-20** | Дополнен §6 (расхождения §6 ↔ SITEMAP устранены). **2FA (MANAGER-only, фича H)**: deps `pyotp` + `qrcode`. `POST /auth/2fa/setup` — генерирует секрет, НЕ сохраняет, возвращает `{secret, otpauth_uri, qr_png_data_url}`; `POST /auth/2fa/enable` `{secret, code}` — проверка TOTP (window=1), сохраняет `users.totp_secret` (поле уже в §5), генерирует 8 recovery-кодов (hex), в БД — только хэши в новой таблице `totp_recovery_codes(user_id, code_hash, used_at)`, plaintext показывается ровно 1 раз (паттерн temp-пароля п.19); аудит `user.2fa.enable`. Логин при включённой 2FA: 200 `{"data": {"two_fa_required": true, "ticket"}}` без кук, ticket — JWT `typ=2fa` TTL 5 мин (только sub, без ролей); `POST /auth/2fa/verify` `{ticket, code}` — код TOTP ИЛИ одноразовый recovery (при использовании помечается `used_at`, не удаляется), rate-limit 5/15 мин, успех → обычные токены+куки+сессия; как второй шаг логина освобождён от CSRF-валидации (логика §16 п.21). `POST /auth/2fa/disable` `{code}` или `{password}` — чистит секрет и recovery; аудит `user.2fa.disable`. CLIENT на 2fa-эндпоинтах → 403; `GET /auth/me` дополняется полем `totp_enabled` (bool, для экрана `/profile/security`). **Сессии (обе роли, фича I)**: `GET /auth/sessions` — свои активные (не revoked/expired): `id, user_agent, ip, created_at, expires_at, current` (сессия с hash refresh-куки); `DELETE /auth/sessions/{id}` — своя сессия (чужая → 404), текущая — отзыв + очистка кук; `DELETE /auth/sessions` — все кроме текущей. Экраны: `/profile/sessions`, `/profile/security`, ветка 2FA на `/login` — по SITEMAP. |
| 23 | Этап 10 «Observability и тесты»: рамка MVP | **Согласовано 2026-08-20** | Уточнение §12/§13 (переносы помечены в §12). **Входит в Этап 10:** (1) API-метрики — `prometheus-fastapi-instrumentator`, `/metrics` на app, nginx проксирует `/metrics` (в prod ограничить доступ, Этап 11); (2) Celery-метрики через **Pushgateway**: worker пушит по сигналам длительность/провалы задач (`prometheus_client.push_to_gateway`, fail-open), beat каждые 30 с пушит глубину очереди (`LLEN` Redis); (3) overlay `infra/docker-compose.observability.yml` (`make obs-up`): Prometheus (scrape: api, pushgateway) + Grafana (provisioning: datasource + 2 дашборда «API» и «Celery/Импорты») + Alertmanager (правила §12: error rate >1%/5 мин; очередь >100; провал импорта; рост 5xx; instance down) + Pushgateway; (4) E2E Playwright в `apps/web/e2e` (сценарии §13: логин клиента, фильтр каталога, экспорт, оформление заявки, импорт менеджером), `npm run test:e2e`, host-run против dev-стека :8080; (5) k6-скрипты `infra/k6/` (каталог 100 RPS с порогами; сценарий импорта), запуск опционален при наличии k6 на хосте. **Перенесено в Этап 11:** Loki (JSON-логи уже в stdout), Tempo/OTel, Uptime Kuma, внешний TLS-доступ к мониторингу, CI-пайплайн (§14). |
| 24 | Этап 11 «Деплой в prod» + Этап 11.5 «1С-заглушки»: рамка | **Согласовано 2026-08-20** | (1) **1С (§18, Этап 11.5)**: subroute `/api/integrations/1c` (вне `/api/v1`, отдельный include на app); 4 эндпоинта §18.2 → `501` + JSON `{detail, schema_version}`; авторизация: заголовок `X-Integration-Token` (constant-time сравнение с `settings.integration_1c_token`) и IP-allowlist (`settings.integration_1c_ip_allowlist`, CSV) → 401/403; пустой токен в настройках → `503` «интеграция не настроена»; попытки логируются structlog, `audit_log` exchange-операций — при реальной реализации (не на заглушках); DTO Pydantic в `app/schemas/commerceml/` (JSON-адаптация CommerceML 2.x; `orders.external_id`/`products.external_1c_guid` уже в §5). (2) **TLS/nginx**: prod — отдельный self-contained `infra/nginx/nginx.prod.conf`: :80 → redirect https, :443 TLS1.3-only + HSTS (§11), `/metrics` allow приватные сети + deny all, `/healthz`/`/readyz` открыты; сертификаты в `infra/nginx/certs/` (gitignore); `make gen-self-signed-certs` для валидации конфига, боевые — Let's Encrypt/вручную (RUNBOOK). (3) **Бэкапы**: MVP — `make backup` (nightly `pg_dump -Fc`) в `infra/backups/` + retention 30 д.; restore-test по RUNBOOK; WAL-G/PITR, MinIO versioning/replication — пост-MVP (разночтение §2/§11/§14 решено). (4) **Prod-харднинг**: db/redis/minio в prod не публикуют порты (ports reset в prod-overlay); вход только через nginx; Makefile `prod-up/prod-down/prod-logs/prod-migrate` через `DC_PROD`. (5) **CI** (`.github/workflows/ci.yml`, §14): lint (ruff+eslint) → test (pytest, сервисы postgres/redis) → security (bandit+pip-audit) → build (docker build api/web; registry — пост-MVP). Playwright-e2e и migrate/deploy вне CI: e2e локально `make test-e2e`, deploy вручную по RUNBOOK (миграции с approve, §14). Выбор РБ-провайдера/домена — при реальном деплое (§19). (6) **RUNBOOK**: `docs/RUNBOOK.md` — deploy/rollback, миграции, бэкап/восстановление + restore-test, TLS-сертификаты, мониторинг (`obs-up`), действия по алёртам §12. |
| 25 | PDF-экспорт: каталог + заявка (фича F) | **Согласовано 2026-08-21** | Закрывает отложенное п.16 («pdf → 422») и фичу §16.1 F. (1) **Deps**: `weasyprint==62.3` (раскомментирован) + системные Pango/HarfBuzz/шрифты DejaVu в Dockerfile stages base и runtime (после purge build-essential, не удаляются). (2) **Каталог**: `POST /catalog/export?format=pdf` — 422-заглушка снята; таск рендерит HTML (Jinja2-шаблон `app/templates/pdf/catalog.j2`, autoescape) → weasyprint → S3 `export/{job_id}.pdf` (`application/pdf`), job-паттерн п.16 без изменений; rate-limit 10/час общий. (3) **Заявка (F)**: job-паттерн вместо синхронного `GET /orders/{id}/pdf` из SITEMAP (GET с side-effect недопустим): `POST /orders/{id}/pdf` → 202 `{job_id}` + `GET /orders/export/{job_id}` — статус/presigned (SITEMAP исправлен); доступ: клиент-владелец или MANAGER; S3 `export/order-{order_id}-{job_id}.pdf`, TTL те же; rate-limit 10/час. Шаблон `app/templates/pdf/order.j2`: реквизиты клиента (company/full_name/phone/email — УНП/адрес в модели нет, при появлении полей добавить в шаблон), позиции из `product_snapshot` (sku/name/brand) + quantity/unit_price (замороженные), total_amount, курс (rate_source/exchange_rate), статус, номер/дата. (4) **Frontend**: в меню «Экспорт» каталога пункт PDF; кнопка «Скачать PDF» на `/orders/[id]` и per-row в `/orders` (poll job → открытие presigned). |
| 26 | SSE-стрим уведомлений (снятие отложения из п.20) | **Согласовано 2026-08-21** | Supersedes «SSE-stream отложен» в п.20 (pull остаётся fallback). (1) **Транспорт**: `GET /notifications/stream` — `text/event-stream`; авторизация по cookie `access_token` на момент коннекта (query-токен исключён — логи); долгоживущий коннект переживает истечение access (переподключение на drop — EventSource авто-reconnect; при 401 фронт уходит в pull). (2) **Доставка**: Redis pub/sub (§3:118) — `repositories/notifications.create_notification` остаётся чистым, publish в новой точке `services/notification_events.py` `publish_notification(notification)` (fail-open: Redis-ошибка → только лог); каналы `notif:user:{id}` и `notif:broadcast` (user_id=None — менеджерский broadcast: PRICE_CHANGED, RATE_FETCH_FAILED); SSE-подписчик: свой канал + broadcast при role=MANAGER. Вызовы publish добавляются рядом с 4 существующими create_notification (tasks/notifications ×2, fetch_nbrb_rates, services/manager_users) и во все будущие. (3) **Протокол**: событие `notification` (JSON: id/type/title/body/created_at), heartbeat-комментарий `: ping` каждые 20 с; client → закрытие при logout. (4) **nginx**: `location ^~ /api/v1/notifications/stream` (до `/api/`) в обоих конфигах: `proxy_buffering off; proxy_cache off; proxy_read_timeout 3600s; proxy_http_version 1.1; Connection ""`. (5) **Frontend**: `useNotifications` + `startStream()` (EventSource same-origin — куки идут сами): onmessage → `unreadCount++`; onerror → close + возврат к существующему poll (60 с); AppHeader стартует stream, poll — fallback. |
| 27 | Этап 12 «Telegram Mini App»: рамка | **Согласовано 2026-08-25** | (1) **Линк вместо автосоздания**: публичной регистрации нет (п.4 — аккаунты создаёт менеджер), поэтому `users.telegram_id` (BIGINT, UNIQUE, nullable; миграция) связывается **одноразовым кодом**: клиент в веб-кабинете (`POST /api/v1/auth/telegram/link-code`, 6 цифр, Redis TTL 10 мин, одноразовый) вводит его при первом входе в m-app (`POST /api/m/v1/auth/telegram {init_data, link_code?}`); повторные входы — по `initData` (найден `telegram_id`). `telegram_chat_id` отдельно не хранится (приватный чат: chat_id == user.id) — поле `telegram_id` используется и для будущих клиентских TG-уведомлений (§20.3). MANAGER линк запрещён (m-app — клиентский путь). (2) **Валидация initData**: `secret = HMAC_SHA256("WebAppData", bot_token)`, `hash = HMAC(secret, data_check_string)` constant-time; пустой `telegram_bot_token` → 503 «не настроено»; `auth_date` старше 24 ч → 401 (replay-окно). (3) **Сессия**: после валидации — тот же путь, что при логине (`_issue_new_session`: access+refresh+Session+куки, §16 п.22-паттерн); m-фронт ходит с `Authorization: Bearer` (CSRF не применяется, §11); m-auth-POST — CSRF-exempt (логика п.21: креды = подписанные initData, не ambient-куки). (4) **API**: отдельного подмножества `/m/v1/**` не создаём — m-app потребляет существующие `/api/v1/**` (отклонение от §6-черновика «тонкое подмножество» в пользу DRY; JSON-контракт мобильно-агностичен). (5) **Frontend**: `layouts/miniapp.vue` (mobile-only, safe-area, без шапки/sidebar); SDK telegram-web-app.js; экраны по SITEMAP §8 (каталог-плитка с поиском/брендом, карточка, корзина+checkout, последние 10 заявок, уведомления); `middleware/m-auth` — неаутентифицированному показывается экран связки (не редирект на /login); `/m/**` добавляется в SKIP_PATHS consent.global (consent принимается в вебе, повторно в webview не требуется). (6) **Rate limit**: m-auth 5/15 мин (аналог login, §11). HTTPS для домена m-app — требование Telegram, деплой-вопрос (RUNBOOK). |
| 28 | Security-hardening бэкенда (по итогам аудита) | **Согласовано 2026-08-26** | Backfill решений, применённых в коде 2026-08-25, + сопутствующие правки техдолга. (1) **Lockout брутфорса**: после `LOGIN_MAX_ATTEMPTS` неудачных логинов по email — блокировка на `LOGIN_LOCKOUT_MINUTES` в Redis; проверка выполняется до rate-limiter. (2) **Кэш сессий**: живость сессии кэшируется в Redis TTL 60 с; отзыв (`invalidate_session`) удаляет ключ немедленно. (3) **Поиск каталога**: LIKE-метасимволы экранируются (`_like_escape` в repositories/catalog.py); pg_trgm GIN-индексы — §5.2. (4) **Health-эндпоинты** (`/healthz`, `/readyz`) не раскрывают env/конфигурацию. (5) **PATCH /auth/me**: whitelist полей — setattr только по разрешённым колонкам User (mass-assignment guard). (6) **App-hardening** (main.py): Swagger/OpenAPI отключаются в prod, CORS из allowlist (без `*`), security-headers, лимит JSON-тела 1 МБ, X-Request-ID + structlog context. Сопровождающие правки пакета: CVE-обновления `python-multipart==0.0.20` (CVE-2024-53981) и `python-jose==3.4.0` (CVE-2024-33663/33664); SQL из `api/miniapp.py` → `repositories/users.get_by_telegram_id`; доменная логика diff/digest перенесена из `repositories/price_changes.py` в новый `services/price_changes.py` (соответствие §4); дедупликация Celery boilerplate → общий `tasks/_common.py`; креды Grafana — через env (`GF_SECURITY_ADMIN_*`, дефолт admin — dev-only). |
| 29 | Публичная SEO-витрина каталога | **Согласовано 2026-08-26** | Цель — органический трафик Яндекса/Google по бренду/артикулу с конверсией в регистрацию. **Только публичные данные без цен/остатков/скидок/ПДн.** (1) API (read-only, без авторизации, envelope и пагинация §6): `GET /api/v1/public/brands` → `{data: [{id, name, slug}]}` — бренды, имеющие неархивные товары; `GET /api/v1/public/brands/{slug}` → `{data: {id, name, slug, series: [{id, name, slug, photo_thumb}]}}` (404 если бренд пуст); `GET /api/v1/public/series/{slug}/products?page&page_size` → `{data: [{sku, name, photo}]}` — только неархивные (photo: личное фото товара, дополнено 2026-09-08 для витрины лендинга). Кэш Redis тегом `catalog` (инвалидация импортом, §7.2); rate-limit 60/мин на IP; CSRF не применяется (GET). Thumb-фото серий — `GET /api/v1/public/photo?key=` (валидация префикса/суффикса → 307 presigned). Slug серии — вычисляемый (нормализация имени `_slugify`, без колонки в БД); коллизии нормализованных имён разрешаются детерминированно (первая по алфавиту); физический уникальный slug — при необходимости отдельной миграцией. (2) Frontend (SSR): страницы `/brands` (все бренды, плитки) и `/brands/[slug]` (бренд: серии с фото-thumb + список SKU, CTA «Войти в кабинет» → `/login`); `useSeoMeta` (title/description/OG); анонимный доступ мимо consent/auth-middleware. (3) Индексация: `robots.txt` (Allow `/`, `/brands`; Disallow приватных зон), server-route `/sitemap.xml` (статика + бренды, кэш 24 ч, fail-open), `noindex` в head авторизованных лейаутов (client/manager/miniapp). |
| 30 | Pre-deploy hardening: куки, CSP, секреты, шифрование at rest, бэкапы как код | **Согласовано 2026-08-26** | (1) **Кука access-токена**: флаг `Secure` при prod (`COOKIE_SECURE=true` в prod-compose/.env); SameSite=Lax уже задан. Полный переход access на httpOnly (BFF-паттерн) — пост-MVP: ломает Bearer-клиентов m-app; остаточный XSS-риск принят осознанно и снижается CSP. (2) **CSP**: заголовок `Content-Security-Policy-Report-Only` из конфига (`CONTENT_SECURITY_POLICY`, дефолт self-политика с unsafe-inline для Nuxt-payload; пусто = выключено); перевод в enforcing — после прогона отчётов на проде. (3) **Секреты**: `.env.prod.template` — чек-лист всех переменных с генерацией через `openssl rand` (SECRET_KEY, пароли БД/MinIO/Grafana), chmod 600, порядок — RUNBOOK. (4) **Шифрование at rest**: требование к VPS — шифрованный диск/LUKS у провайдера или включение шифрования тома (RUNBOOK, шаг деплоя); MinIO versioning/WAL-G — пост-MVP (п.24). (5) **Бэкапы как код**: `infra/scripts/restore_db.sh` + `make restore-test` (проверка дампа восстановлением во временную БД), systemd unit+timer для nightly backup вместо ручного cron. (6) **Healthchecks** api/web/nginx в dev- и prod-compose. |

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

> **Текущая версия документа:** v1.5
> **Сопутствующие файлы:** `SITEMAP.md` (карта сайта/экранов).
