# Frontend design & UX audit — apps/web (Nuxt 3)

## 1. Design system
- **No UI kit.** No Nuxt UI / PrimeVue / Headless / shadcn package in `apps/web/package.json` — only `nuxt`, `@nuxt/icon`, `@pinia/nuxt`, `@nuxtjs/color-mode`, `@nuxtjs/tailwindcss`, `zod`. Primitives are hand-rolled shadcn-flavoured.
- Tailwind v3.4.13, `apps/web/tailwind.config.ts`: `darkMode: 'class'`; **no plugins**; only spacing override is `18: 4.5rem`.
- **Tokens** as RGB triplets in `apps/web/assets/css/main.css:16-90` (`:root`) / `:92-128` (`.dark`). Semantic roles only: `background`, `surface`, `surface-2`, `surface-raised`, `service`(+`-2/-ink/-muted/-border`), `ink`(+`muted`), `border`/`border-strong`, `action`(+`hover/soft/on`), `success`/`warning`/`danger`/`info` (each `DEFAULT/soft/text`), `focus`.
- Palette (light): warm paper bg `245 242 235`, dark-green chrome `27 42 36` (service), terracotta action `198 92 59`, focus ring `27 111 138`. Dark set fully defined.
- **Typography:** Manrope (sans **and** display), IBM Plex Mono (`numeric` util, tabular-nums) — `apps/web/nuxt.config.ts:110` Google Fonts `<link>` + preconnect. Custom scale: xs .75 / sm .875 / base 1 / lg 1.125 / xl **1.5** / 2xl **1.5 (duplicate)** / 3xl 1.875 — **no 4xl–9xl**; any `text-4xl`/`text-5xl` is unstyled Tailwind default. Non-standard weights 450, 750.
- **Radii intentionally square:** `--radius-control: 0`, `--radius-surface/dialog: 2px`, `--radius-pill: 0`.
- **Shadows suppressed:** `card: none`, `card-hover: none`; only `overlay` + `sticky`. `transitionTimingFunction.trade = cubic-bezier(.2,0,0,1)`.
- **Effects explicitly killed** for the "trade" look: `main.css:352-370` zeroes `hero-orb`, `accent-glow`, `animated-gradient-text`, `section-gradient-*`, `ui-fade-in`, `img-fade`, `tilt-card`. Global `prefers-reduced-motion` reset at `:377-385`.
- **Legacy aliases retained on purpose** ("пока миграция layout не завершена", `:63-84`): `--color-canvas`, `--color-primary*`, `--color-glass*`, `--shadow-card*`.
- `assets/css/landing.css` — 1401 lines, everything scoped under one `.landing-trade` namespace class; section 2 is "Concept 05 — modern trade overrides from the original prototype".
- **Icons:** `@nuxt/icon`, `serverBundle:'local'` + client scan incl. `.ts` (icon names live in nav arrays), 85 unique `heroicons:*` + 2 `simple-icons:*` (telegram, whatsapp).
- **Dual component registration** — `nuxt.config.ts:56-63` registers `~/components` unprefixed **and** `~/components/ui` with `Ui` prefix, so `<Button>` and `<UiButton>` both resolve.
- **Primitives in `apps/web/components/ui/`** (22): `Button, IconButton, Input, Textarea, Field, Checkbox, RadioGroup, Select, Menu, SegmentedControl, Panel, Dialog, Sheet, Spinner, Skeleton, LoadingState, ErrorState, UiEmptyState, StatusBadge, TableFrame, SortableHeader, Pagination, ToastViewport`.
  - `Button`: variant `primary|secondary|outline|ghost|danger`, size `compact|default|touch`, `loading`, `disabled` (`components/ui/Button.vue:2-29`).
  - `TableFrame`: `caption`, `stickyHeader` (default **false**), `compact`, `overflow-x-auto`.
- **Consistency: MEDIUM-LOW.** Adoption counts: `UiErrorState` 48, `UiButton` 74, `UiField` 27, `UiSkeleton` 23, `UiStatusBadge` 23, `UiInput` 15, `UiPanel` 7, `UiSelect` 5, `UiPagination` 3, `UiTableFrame` 3 (only `files`, `orders/index`, `catalog/index`).
  - **Unused primitives:** `UiSortableHeader`, `UiRadioGroup`, `UiMenu`, `UiSegmentedControl` = **0 usages**; `UiDialog` = 1.
  - **Legacy `.btn/.btn-primary/.btn-*` CSS still used 66×** → two parallel button systems.
  - **Duplicate components:** `components/EmptyState.vue` (21) vs `components/ui/UiEmptyState.vue` (34); `components/BaseSelect.vue` (157) vs `components/ui/Select.vue` (250); `components/ToastContainer.vue` (54, **mounted nowhere**) vs `components/ui/ToastViewport.vue` (71, global in `app.vue:8`); `AppHeader.vue`/`AppSidebar.vue` (legacy) vs `layout/ClientHeader.vue`/`ClientSidebar.vue`.

## 2. Layouts & navigation (5)
- `layouts/default.vue` — PublicHeader (sticky dark) + PublicFooter; **skip-link → `#main-content`**; `AppOfflineBanner`.
- `layouts/auth.vue` — split: left dark service panel with numbered 3-step explainer + header; right `max-w-md` form; `noindex,nofollow`; no nav, footer only.
- `layouts/client.vue` — `MobileClientHeader`(<lg) + `ClientHeader`(lg+), `ClientSidebar` (lg only, sticky w-64), `CurrentRequestStrip` above content, `RequestReviewSheet`, `MobileClientNav` bottom bar; `noindex`.
- `layouts/manager.vue` — sticky dark header (role badge, logout) + 13-item sticky sidebar w-60 (lg); `/manager/admin` bottom-pinned for ADMIN; **mobile = horizontal scroll nav bar, not bottom nav**; `noindex`.
- `layouts/miniapp.vue` — fixed 4-item bottom nav (Каталог/Корзина/Заявки/События) w/ count badges, `max-w-md`, safe-area insets, injects `telegram-web-app.js`; `noindex`.
- Client nav sections: «Работа» (Кабинет/Каталог/Текущая заявка/История заявок) + «Справочники» (Избранное/Документы/Аналитика) — `components/layout/ClientSidebar.vue:3-20`.
- **Role switching: no UI.** Enforced via `middleware/role.ts` + `roles:[...]` in `definePageMeta`. Only `pages/notifications.vue:6-15` picks layout dynamically (`auth.isManager ? 'manager' : 'client'`).
- **Breadcrumbs: ABSENT** — zero matches anywhere.

## 3. Pages inventory (49 files, ~13.6k lines)
**Public** (no `definePageMeta` → default layout)
- `pages/index.vue` 383 — SEO landing, brand showcase, FAQ, metrics/testimonials/video. High.
- `brands/index.vue` 96 — public brand list, `useSeoMeta`. Low. `brands/[slug].vue` 170 — brand series + products **without prices**. Med.
- `news/index.vue` 111 — public news list, paginated. Low. `news/[id].vue` 107 — article. Low.
- `privacy.vue` 110 — ПДн policy. Low.
**Auth** — `login.vue` 257 (med), `reset-password.vue` 107, `force-change-password.vue` 104, `consent.vue` 77 (ПДн consent). Auth layout.
**Client** — `catalog/index.vue` 556 **high** (search/filters/sort/cursor pagination, mobile record list + xl table); `catalog/[sku].vue` 421 **high**; `bulk-add.vue` 551 **high** (SKU-paste, ≤500, batches of 8); `checkout.vue` 402 **high**; `analytics.vue` 439 high; `orders/index.vue` 351 high; `favorites.vue` 323 med; `files.vue` 259 med; `notifications.vue` 267 med; `profile/index.vue` 246, `profile/security.vue` 261 (2FA), `profile/sessions.vue` 179, `profile/organization.vue` 149, `profile/notifications.vue` 129; `cart.vue` 188 med; `orders/[id].vue` 222 med; `dashboard.vue` **14 = thin wrapper** by design (content in `components/client/ClientHomeDashboard.vue`).
**Mini-app** — `m/index.vue` 104 (login), `m/catalog/[sku].vue` 185, `m/cart.vue` 168, `m/catalog/index.vue` 170, `m/notifications.vue` 99, `m/orders/index.vue` 97. Small/med, separate API layer.
**Manager** — `manager/import.vue` 846 **highest** (drag&drop CSV + ZIP photos, 100 MB cap, version history, focus-trapped rollback); `manager/users/[id].vue` 618 high; `manager/catalog.vue` 557 high (PATCH override price/stock, POST); `manager/files.vue` 510 high (CRUD, 200 MB, pdf/csv/zip); `manager/brands.vue` 475; `manager/users/index.vue` 424; `manager/banners.vue` 396; `manager/news.vue` 378; `manager/orders/index.vue` 348; `manager/organizations/[id].vue` 335; `manager/admin.vue` 274; `manager/orders/[id].vue` 256; `manager/audit.vue` 250; `manager/currency.vue` 243; `manager/organizations/index.vue` 202; `manager/index.vue` 167; `manager/analytics.vue` 19.
- **Unfinished:** `pages/manager/analytics.vue` — explicit stub, «Раздел недоступен … В API v1 нет подтверждённого контракта», links back to /manager. `pages/dashboard.vue` is a wrapper, not a stub.

## 4. Core UX flows
- **Catalog browsing: PRESENT.** q / brands[] / series[] / stock / model filters, `sort: name|-name|price|-price|sku`, `limit≤100`, cursor + `nextCursor/hasMore`, `priceCalcMode: fixed|nbrb_current` — `domain/api/v2/catalog.schema.ts:9-26`; UI `pages/catalog/index.vue:483-556`.
- **Product card: PRESENT.** `components/commerce/ProductRecordRow.vue` (clientPrice bold, «Цена по запросу» fallback, VolumeTierBadge, StockBadge, ProductPhoto).
- **Personal price visibility: PRESENT.** `clientPrice` shown when `> 0`, else «Цена по запросу»; discounted → strike-through `retailPrice`; volume-tier ladder; exchange-rate source + basePrice — `pages/catalog/[sku].vue:296-330`.
- **Cart / checkout: PRESENT.** `/cart` + `CurrentRequestStrip` + `RequestReviewSheet`; `/checkout` with sticky dark summary `pages/checkout.vue:371`. Client cart = v2 (`useCartV2` + `stores/cart.ts` + `domain/cart`).
- **Orders: PRESENT.** Status tabs + date range + min/max total + activeFilterCount + reset `pages/orders/index.vue:47-140`; detail = `OrderStatusTimeline` + PDF + XLSX export.
- **CSV import: MANAGER-ONLY.** `pages/manager/import.vue` — drag&drop, ext+size validation, CSV price import, ZIP photo import, version list, rollback w/ focus return. **No client CSV import** — client `bulk-add` is SKU-paste into the cart, not a price file.
- **Manager dashboard: PRESENT.** KPI, 30-day orders, tops, recent, manual refresh (server 60 s cache) `pages/manager/index.vue:1-45`.
- **Analytics: client-only.** Hand-rolled inline SVG bar chart + top-products + recent-orders tables `pages/analytics.vue:246-258`. Manager analytics absent.
- **Notifications: PRESENT.** `/notifications`, 9 RU type codes with icons + deep links, read/read-all, unread badge (`composables/useNotifications.ts`). Preferences in `/profile/notifications`.
- **Profile/settings: PRESENT** — index, organization, security (2FA), sessions, notification prefs.
- **Files/documents: PRESENT** — client `/files` read-only (public/authed visibility), manager `/files` CRUD + upload.
- **Other manager CRUD: brands, banners, news, currency, audit, admin (ADMIN only).**

## 5. UX quality
**Tables**
- **Virtualization: ABSENT** (only `composables/useCountUp.ts` uses IntersectionObserver).
- **Sticky header: partial.** `UiTableFrame stickyHeader` exists (default false) but only 3 pages use TableFrame; only `pages/manager/users/[id].vue:444` has `thead.sticky top-0`.
- **Column sort: ABSENT in UI.** `UiSortableHeader` (emits `aria-sort`) has **0 usages**.
- **Bulk select: minimal** — manager/users/[id], manager/catalog, manager/news only.
- **Pagination: mixed.** `UiPagination` 3×; most pages hand-roll `PER_PAGE` + `page` (files 10, notifications 20, news 12); catalog uses cursor, not pages.
- **Export: detail-only.** `usePdfExport`/`useXlsxExport` on `orders/index`(PDF), `orders/[id]`(PDF+XLSX), `manager/orders/[id]`(XLSX). **No list export, no CSV export anywhere.**
**Forms & validation**
- **No validation library** (no vee-validate/yup/zod-form). Hand-rolled checks in `checkout`, `manager/files`, `manager/import`, `news/*`.
- `UiField` 27×, but **`aria-invalid` only in 5 places** (reset-password, force-change-password, profile/security).
- **Toasts: MANAGER-ONLY.** `useToast` imported in 8 pages, all `pages/manager/*`. **Zero toasts in every client and mini-app page** — client feedback is inline `role="alert"` text only.
- **Optimistic UI: ABSENT** (0 matches). Closest: per-row `updatingSku`/`removingSku` local spinners `pages/m/cart.vue:12-13`.
- `UiButton :loading` supported and widely used.
**States**
- Error: strong (`UiErrorState` 48×, `retry` emit). Loading: `UiSkeleton` 23× + 8 skeleton rows in catalog; `UiLoadingState` only 4×. Empty: `UiEmptyState` few usages, no illustrative guidance/tour.
- Global `AppOfflineBanner` = network-loss only (`useOnline`), shown only after confirmed `offline` event — **not offline caching**.
**Responsive**
- Mobile bottom nav: client (4 items + cart count badge, safe-area) and mini-app (4 items). Manager gets a **horizontal scrolling bar**, not a bottom nav.
- Tables degrade via `overflow-x-auto` + a mobile record list only in the catalog; manager tables are horizontally scrollable desktop tables.
- `lg` (1024) is the dominant breakpoint; `container-app` max-w-1440px.
**Accessibility**
- 165 `aria-label`, 171 `aria-hidden`, 55 `aria-labelledby`, 28 `aria-busy`, 12 `aria-live`, 46 `role="alert"`, 6 `role="dialog"`, 5 `aria-sort`.
- Global `focus-visible` 2px outline w/ offset using `--color-focus` `main.css:157-160`; `useFocusTrap` in `UiDialog`, `UiSheet`, `GlobalSearch`; `useBottomLayers`/`useNavLayer` stack toasts above mobile nav.
- **Skip-link exists only in `layouts/default.vue:13`** — absent from client/manager/miniapp.
**Onboarding**
- **Registration/sign-up: ABSENT.** **Invite-acceptance flow: ABSENT** (no page).
- Adjacent mechanisms only: `components/TempPasswordDialog.vue`, `pages/force-change-password.vue`, `pages/consent.vue` + `components/ConsentModal.vue` (ПДн), `pages/login.vue` + `layouts/auth.vue` 3-step explainer.
- **Demo mode / tour / coachmark / checklist: ABSENT.**
**i18n**
- **ABSENT.** No `@nuxtjs/i18n`, no `vue-i18n`, no `useI18n`. All strings hardcoded RU; `htmlAttrs lang="ru"`; `Intl.NumberFormat('ru-RU')` hardcoded.
**SEO / SSR / PWA**
- `ssr: true`; `titleTemplate '%s — Клиентский портал'`; `useSeoMeta` on public brand/news pages; `server/routes/robots.txt.ts` + `sitemap.xml.ts` present; og meta on public pages, **no `og:image` in default head** (only `public/og-landing.png` exists).
- Noindex applied by auth/client/manager/miniapp layouts.
- **PWA: ABSENT.** No `manifest.webmanifest`, no service worker, no `@vite-pwa/nuxt`; `experimental.appManifest: false` explicitly `nuxt.config.ts:130-135`.
**Dark mode**
- Fully tokenized + `.dark` class + `@nuxtjs/color-mode`, **but `preference: 'light'`, `fallback: 'light'`, no `system`** `nuxt.config.ts:65-71`. Toggle (`useTheme`) present in `PublicHeader`, `ClientHeader`, `MobileClientHeader` — **absent from manager and miniapp layouts**, i.e. unreachable for those roles.
**Telemetry**
- Yandex.Metrika, conditional on `NUXT_PUBLIC_METRIKA_ID` with digits-only validation before `innerHTML` injection `nuxt.config.ts:6-7, 116-121`; clickmap + trackLinks + webvisor + accurateTrackBounce. CSP allows `mc.yandex.ru`. No other telemetry/error tracking.
- Security headers + CSP served by Nitro `server/middleware/security-headers.ts` (enforcing, with documented `unsafe-inline` tradeoff).
- Tests: 25 vitest specs + 5 Playwright specs (18 e2e tests) incl. `offline.spec.ts`, `security-headers.spec.ts`, `navigation.spec.ts`, `icon-set-contract.spec.ts`.

## 6. Telegram mini-app
- Routes `/m/*`, `layouts/miniapp.vue`, `middleware/m-auth.ts`, injected `https://telegram.org/js/telegram-web-app.js`.
- **Separate v1 stack:** uses `composables/useCart.ts` (module state, `~/types/api.ts` snake_case `CartItemRead`/`OrderRead`) — **completely independent from the browser v2 cart** (`useCartV2` + `stores/cart.ts` + `domain/api/v2/*` zod camelCase schemas). Browser cart and mini-app cart never mix.
- **Simplified price logic:** `p.has_discount ? p.client_price : p.retail_price` (`pages/m/catalog/index.vue:27`, `pages/m/catalog/[sku].vue:165-166`) — no `hasDisplayPrice()`, no volume tiers, no exchange-rate/base-price display, no `priceCalcMode`.
- **Auth:** `pages/m/index.vue` — Telegram `initData` auto-auth with manual **link-code** fallback form; `useTelegram` provides `initData()`, `waitForInitData(4000 ms poll)`, `ready()`/`expand()`, `telegramAuth(linkCode)`. **No** BackButton, MainButton, Haptics, or themeParams mapping.
- **Checkout is inlined** into `/m/cart` as a 3-stage state machine `cart | checkout | done` — no separate `/m/checkout`.
- **ABSENT in mini-app vs web:** favorites, bulk-add, files/documents, invoices, analytics, profile/settings, brand pages, volume tiers, notification preferences, PDF/XLSX export, currency detail.
- Shared: `AppOfflineBanner`, notification unread badge, same tokens/typography.

---

## TOP GAPS (design/UX)
1. `pages/manager/analytics.vue` is an explicit stub — manager has zero analytics/reporting UI.
2. No column sorting anywhere in the UI: `UiSortableHeader` is built but unused (0 usages).
3. No table virtualization; sticky headers exist as a prop but only 3 of 49 pages use `UiTableFrame`.
4. Toasts exist on 8 manager pages only — every client and mini-app page gives feedback as inline text alone.
5. No list-level export (CSV/XLSX/PDF); export is wired only to order detail.
6. No form-validation library; `aria-invalid` appears on just 5 password fields.
7. No registration or invite-acceptance page — no self-serve onboarding path exists.
8. No breadcrumbs on any page in the product.
9. No PWA: no manifest, no service worker, `experimental.appManifest` explicitly disabled.
10. Dark mode is unreachable for MANAGER and mini-app roles; preference pinned to `light`, no `system`.
11. Two parallel button systems (74 `UiButton` vs 66 legacy `.btn-*` classes) plus duplicate EmptyState/Select/Toast/Sidebar components — `ToastContainer.vue` is dead code.
12. i18n absent — all UI strings hardcoded Russian.
13. Mini-app runs on the legacy v1 snake_case cart/order API with divergent price logic from the web v2 portal.
14. Skip-link present only in the default layout — missing from client, manager and mini-app shells.
15. Manager tables are hand-rolled `<table>` markup outside `UiTableFrame`, with bulk actions only on `manager/users/[id]`.