# Trade Design System

> Канон визуальной системы Price Web. Утверждён 2026-09-24 для полной замены web frontend.
> Документ обязателен для `apps/web`, Telegram Mini App и используется как источник визуальных правил для будущего SwiftUI-клиента.

## 1. Назначение

Trade — плотный, спокойный и технический интерфейс для оптовой торговли. Он должен восприниматься как рабочий инструмент импортёра, магазина и производственной компании, а не как универсальный SaaS-сайт.

Основные свойства:

- табличная плотность и быстрый доступ к SKU, цене, наличию и количеству;
- прямоугольная геометрия без pill/capsule-контейнеров;
- тёплый светлый фон и тёмно-зелёные служебные поверхности;
- терракотовый цвет только для ключевых действий и акцентов;
- ясная семантика статусов, а не декоративные цветовые градиенты;
- полноценная тёмная тема без изменения геометрии;
- desktop-first рабочие сценарии и полноценная адаптивная мобильная версия.

## 2. Токены

### 2.1 Светлая тема — основная

```css
--bg: #f5f2eb;
--surface: #fffdf8;
--surface-2: #e6e9df;
--service: #1b2a24;
--service-2: #24382f;
--ink: #1b2a24;
--ink-on-service: #f8f5ed;
--muted: #65736b;
--line: #c8d0c7;
--line-strong: #9dab9f;
--accent: #c65c3b;
--accent-hover: #a9482d;
--success: #2f7652;
--warning: #a86d19;
--danger: #b6403a;
--info: #35677a;
--focus: #1b6f8a;
```

### 2.2 Тёмная тема

Тёмная тема — самостоятельная адаптация, а не инверсия светлой. Она сохраняет контраст текста, границ и служебных панелей.

Базовые направления:

- canvas — глубокий тёплый тёмный фон;
- основная surface — чуть светлее canvas;
- service surface — ещё темнее и спокойнее основной surface;
- terracotta остаётся акцентом, но его lightness корректируется для контраста;
- line и muted обязаны проходить WCAG AA для обычного текста.

Точные dark values задаются в одном месте `apps/web/assets/css/main.css` после удаления старой системы. До их утверждения компоненты используют только семантические токены.

### 2.3 Семантические роли

UI не должен обращаться к палитре по смыслу конкретного бренда. Компонент использует роль:

- `background`;
- `surface`;
- `surface-raised`;
- `service`;
- `text`;
- `text-muted`;
- `text-inverse`;
- `border`;
- `border-strong`;
- `action`;
- `action-hover`;
- `success`;
- `warning`;
- `danger`;
- `focus`.

Hardcoded `#`, `rgb()` и `rgba()` в Vue-компонентах запрещены. Цвет текста внутри DTO и данных не является частью UI-системы.

Публичная главная использует изолированный слой Trade (см. раздел 2.4), а зелёная шапка и остальные служебные поверхности остаются отдельной зоной бренда.

### 2.4 Публичная главная — концепция 05 Trade

Главная `/` является прямой реконструкцией пятой вкладки `05 Trade` исходного прототипа. Все правила живут в `apps/web/assets/css/landing.css` и доступны только внутри корня `.landing-trade`.

Токены Trade:

```css
--landing-bg: #f5f2eb;
--landing-surface: #fffdf8;
--landing-surface-2: #e6e9df;
--landing-ink: #1b2a24;
--landing-muted: #65736b;
--landing-line: #c8d0c7;
--landing-accent: #c65c3b;
--landing-dark: #1b2a24;
--landing-dark-muted: #afbbb1;
```

Для главной допустимы следующие исходные решения:

- `Manrope` 700–800 для крупных display-заголовков;
- терракотовый акцент только для смысловых и интерактивных элементов;
- жёсткая прямоугольная геометрия и 1 px разделители;
- тёмная техническая панель с сеткой, штампом и жёстким terracotta-shadow;
- responsive-геометрия на 1000 px и 600 px.

За пределами `.landing-trade` эти правила не применяются. `/brands`, новости, кабинет, формы и общие компоненты продолжают использовать семантические токены Trade. Зелёные `PublicHeader` и `PublicFooter` остаются оболочкой сайта.

## 3. Типографика

### 3.1 Семейства

- интерфейс и заголовки: `Manrope`, 400–800;
- SKU, цены, наличие, количество, валюты, курсы, технические идентификаторы и числовые колонки: `IBM Plex Mono`, 400–600;
- системный fallback: `ui-sans-serif`, `system-ui`, `sans-serif`.

IBM Plex Mono подключается как полноценная Tailwind-роль `font-mono` и CSS custom property `--font-mono`.

### 3.2 Шкала

| Роль | Размер | Line height | Вес |
|---|---:|---:|---:|
| Display | 40/48 desktop, 32/38 mobile | — | 750 |
| H1 | 30/38 | — | 750 |
| H2 | 24/32 | — | 700 |
| H3 | 19/26 | — | 700 |
| Body | 16/24 | — | 450 |
| Dense body | 14/20 | — | 500 |
| Table | 13/18 | — | 500 |
| Metadata | 12/17 | — | 600 |
| Mono numeric | 13/18 | — | 500 |

Минимальный пользовательский текст — 12 px. Декоративные подписи меньше 12 px запрещены.

Числовые колонки используют `font-variant-numeric: tabular-nums` и выравнивание по правому краю.

## 4. Геометрия

### 4.1 Радиусы

```css
--radius-control: 0;
--radius-surface: 2px;
--radius-dialog: 2px;
--radius-pill: 0;
```

- контейнеры, поля, кнопки, ссылки-контролы, бейджи, вкладки и навигация: 0–2 px;
- pill/capsule UI запрещён;
- круг разрешён только для spinner, avatar, status-dot и круглой icon-only кнопки;
- круглый avatar не должен становиться круглой карточкой контента.

### 4.2 Границы и тени

- обычный border: 1 px solid `--line`;
- усиленный border: 1 px solid `--line-strong`;
- тень применяется только к dropdown, popover, dialog, drawer и sticky action bar;
- тень жёсткая и минимальная, не размывает таблицу;
- декоративные тени карточек, hover lift и glow запрещены.

### 4.3 Spacing

Базовый шаг — 4 px. Основные интервалы: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

- контролы: высота 36 px, compact 32 px, touch 44 px;
- dense table row: 44–48 px;
- обычный form row: высота не менее 44 px на мобильном;
- page gutter: 16 px mobile, 24 px tablet, 32 px desktop;
- content max width: 1440 px, широкие таблицы могут использовать весь viewport с горизонтальным scroll внутри табличной области.

## 5. Layout

### 5.1 Desktop

- фиксированная или sticky левая навигация 224–248 px для client/manager;
- header содержит логотип, глобальный поиск, валюту, уведомления, заявку/корзину и профиль;
- рабочая область состоит из page heading, action bar, filter/toolbar и данных;
- таблица является основным способом работы оптового пользователя;
- фильтры используют left rail или вынесенный filter panel, но не floating glass;
- manager-экраны используют тёмно-зелёный service sidebar и светлую рабочую область.

### 5.2 Tablet

- sidebar сворачивается в icon rail или заменяется top navigation;
- filter panel может открываться как side sheet;
- таблица сохраняет ключевые колонки, второстепенные переходят в detail expansion;
- sticky header допустим только с непрозрачным фоном.

### 5.3 Mobile

- обычная мобильная версия — адаптация тех же маршрутов, а не уменьшенный manager desktop;
- header: логотип/роль, поиск, корзина или заявка;
- bottom navigation — плоская закреплённая полоса, безопасная зона учитывается снизу;
- каталог поддерживает list и grid, по умолчанию используется list при узком viewport;
- фильтры открываются rectangular bottom sheet;
- checkout использует sticky action bar с итогом и кнопкой;
- горизонтальный overflow запрещён для страницы, но разрешён внутри ограниченной табличной области с доступным horizontal scroll.

## 6. Компоненты

### 6.1 Buttons

- rectangular;
- primary — terracotta, только одна главная операция на экранном контексте;
- secondary — surface + border;
- danger — danger color для необратимой операции;
- loading сохраняет размеры и использует spinner или линейный progress;
- disabled состояние не исчезает и сохраняет доступный label.

### 6.2 Fields

- label всегда связан с control;
- helper/error связаны через `aria-describedby`;
- ошибка не исчезает после blur, если пользователь не исправил значение;
- focus-visible — контрастная обводка или inset ring, не glow;
- select, checkbox, radio и date input используют собственные rectangular primitives.

### 6.3 Tables

Рекомендуемый порядок колонок:

1. selection/action;
2. product image + name;
3. SKU;
4. brand/series;
5. availability;
6. price;
7. quantity;
8. line total;
9. action.

- server-side sort отображается в header;
- текущий сортирующий столбец объявляется `aria-sort`;
- sticky header может быть непрозрачным;
- на mobile строка превращается в компактный record row с SKU, name, price, stock и действиями.

### 6.4 Product record

- media — реальное фото или нейтральный placeholder;
- SKU и цена всегда читаются независимо от длины названия;
- stock status — отдельный смысловой элемент;
- действие добавления всегда доступно без скрытых hover-only controls.

### 6.5 Status badge

Badge имеет прямоугольную форму, border и короткий label. Цвет никогда не является единственным носителем статуса.

### 6.6 Dialogs и drawers

- используются только для короткой подтверждаемой задачи;
- title и close action доступны клавиатурно;
- destructive action требует явного confirm;
- body не является floating glass card;
- mobile full-screen/sheet вариант использует safe area.

### 6.7 Toast и async state

- toast — плоская rectangular строка;
- job progress показывает статус, процент/счётчик и link/retry;
- polling остаётся в domain service, UI только отображает состояние;
- SSE недоступен — polling fallback без дублирования источников.

### 6.8 Empty, error и loading

- empty: заголовок, объяснение, одно основное действие;
- error: problem summary, code для поддержки, retry;
- loading skeleton повторяет форму будущего контента;
- shimmer запрещён;
- offline/banner должен быть компактным и не перекрывать sticky actions.

## 7. Запрещённые паттерны

- `rounded-pill`, capsule buttons/chips/badges;
- карточки с радиусом 16–24 px;
- floating glass navigation/cards;
- `backdrop-filter` как базовый материал UI;
- ambient radial gradients и декоративные orb;
- generic purple/blue SaaS accents;
- emoji как основная бизнес-иконка;
- hover-only доступные действия;
- skeleton/shimmer для маленьких динамических числовых строк;
- layout, смысл которого зависит от одной только иконки или цвета.

## 8. Доступность

- WCAG 2.2 AA для текста, controls, focus и status;
- keyboard navigation для всех ссылок, таблиц, dialogs, sheets и menus;
- focus-visible на каждом интерактивном элементе;
- touch target не менее 44 px на mobile;
- `aria-sort`, `aria-current`, `aria-expanded`, `aria-selected` используются по назначению;
- modal focus trap и возврат фокуса обязательны;
- `prefers-reduced-motion: reduce` отключает transform/opacity transitions длительнее 120 ms;
- текст масштабируется до 200% без потери функций и двустороннего scroll всего документа;
- изображения имеют alt; декоративные изображения скрыты от screen reader.

## 9. Тема и сохранение выбора

- новая система стартует в light mode;
- fallback темы — light;
- используется новый storage key, чтобы старая сохранённая dark preference не переключала новую систему автоматически;
- theme toggle доступен в desktop header и mobile account menu;
- тема меняет токены, а не структуру DOM.

## 10. Реализация в Nuxt

Ожидаемая структура:

```text
apps/web/assets/css/main.css          # token layer
apps/web/tailwind.config.ts            # semantic colors, font roles, radius limits
apps/web/components/ui/                # primitives
apps/web/components/layout/            # shells
apps/web/composables/useTheme.ts       # light/dark
apps/web/composables/useMediaQuery.ts  # responsive behavior
```

Старые `.glass`, `.card`, rounded token, ambient body background и локальные hardcoded overrides удаляются во время замены shell, а не остаются как скрытый fallback.

## 11. Канонические пространства и иерархия

Trade — не одна универсальная сетка карточек. Производственный интерфейс состоит из четырёх самостоятельных мобильных пространств, которые используют одни и те же domain-данные и v2-команды:

1. **Каталог** — приветствие и контекст клиента, search-first поиск, быстрые действия, горизонтальные категории, затем record-list товаров и cursor pagination. На телефоне первичным является `ProductRecordRow`; desktop показывает плотные записи или таблицу.
2. **Текущая заявка** — статусная строка, `OrderLineRecord`, тёмный блок итога и одно primary action. Редактирование количества и удаление позиций доступны непосредственно в строке, а не в скрытом hover-меню.
3. **Кабинет** — реальные показатели, последние заявки, документы и навигационные записи. Промо и новости не должны конкурировать с рабочими данными.
4. **Профиль** — master record клиента и последовательные плоские разделы: организация и условия, валюта, уведомления, Telegram, безопасность и выход.

Checkout, история заявок, документы, избранное и фильтры являются расширениями этих пространств, а не новыми визуальными жанрами. Они наследуют ту же record/list иерархию.

На desktop те же маршруты получают header/sidebar и плотные таблицы, но не отдельную логику или другую модель данных. На mobile нижняя навигация всегда состоит из четырёх destination: «Каталог», «Заявка», «Кабинет», «Профиль» и учитывает safe area.

Telegram Mini App — отдельный channel. Он использует собственную v1 auth/catalog/cart композицию и никогда не подключает browser cart v2. Визуально он следует record/list правилам, но не получает client sidebar и desktop-композицию.

`price-web-samples/mobile.html` и связанные demo-файлы являются reference-only: они задают иерархию, плотность и touch behavior, но их данные, demo session, `localStorage`, фиктивные auth/CRM hooks, недоступные действия и presentation store не переносятся в production.

## 12. Миграция маршрутов и канонические компоненты

Trade-система применяется не только к публичной главной. Внутренние поверхности используют общий token layer из `apps/web/assets/css/main.css` и `apps/web/tailwind.config.ts`; изолированные правила `landing.css` не импортируются в client, manager или Mini App.

Канонические общие компоненты:

- `components/layout/PageHeading.vue` — eyebrow, один H1, описание и actions для всех внутренних страниц;
- `components/ui/UiPanel.vue` — плоская bordered surface;
- `components/ui/UiEmptyState.vue`, `UiErrorState.vue`, `UiLoadingState.vue` — единые loading/error/empty состояния;
- `components/ui/UiButton.vue`, `UiField.vue`, `UiInput.vue`, `UiCheckbox.vue` — общие формы и действия;
- `components/ui/UiStatusBadge.vue` — единый статус без зависимости от одного цвета;
- `components/ui/TableFrame.vue`, `UiPagination.vue`, `UiSortableHeader.vue` — плотные таблицы и навигация по ним;
- `components/ui/ToastViewport.vue` — единственный глобальный toast viewport с `aria-live` и safe-area positioning;
- `components/ui/Dialog.vue` и `Sheet.vue` — общий modal/sheet contract с focus trap, Escape, overlay close и restoration focus;
- `utils/order-status.ts` — общие labels и tones для статусов заявок.

Маршрутные правила:

- `/` и `landing.css` остаются прямой реконструкцией `05 Trade` и используют только реальные public API v1 данные;
- зелёные `PublicHeader`/`PublicFooter` остаются публичной оболочкой;
- client, manager и auth/legal используют `PageHeading` и semantic roles, сохраняя browser API v2, permissions и navigation;
- Telegram Mini App использует отдельные v1 auth/catalog/cart и bottom navigation, но общие `PageHeading`, status badges, fields, record rows и Trade tokens;
- fake testimonials, fake metrics, demo stores, `localStorage` и private commerce API на landing запрещены.

После миграции старые `EmptyState`, `ToastContainer` и локальные status maps не должны подключаться новыми страницами. Их удаление выполняется только после подтверждения отсутствия активных потребителей.

## 13. Приёмка

Дизайн-система принята, если:

- в production build отсутствуют pill/capsule containers;
- радиусы контейнеров не превышают 2 px, кроме разрешённых круглых элементов;
- нет ambient orbs, gradient glow и default glass;
- light и dark соответствуют токенам;
- таблицы читаются на 1280 px и 390 px;
- нет горизонтального overflow страницы;
- keyboard focus виден и логичен;
- status доступен без цвета;
- loading/empty/error/success/offline реализованы;
- color/font/radius не захардкожены в page templates.
