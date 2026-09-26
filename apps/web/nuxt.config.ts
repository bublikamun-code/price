// https://nuxt.com/docs/api/configuration/nuxt-config
// См. ARCHITECTURE_PLAN.md §3 (дизайн), SITEMAP.md §1 (роутинг/layouts).

// Номер счётчика Метрики: только цифры. Значение попадает в innerHTML тела
// скрипта, поэтому всё, что не цифры, стало бы исполняемым JS.
const rawMetrikaId = process.env.NUXT_PUBLIC_METRIKA_ID?.trim() ?? ''
const METRIKA_ID = /^\d{1,12}$/.test(rawMetrikaId) ? rawMetrikaId : ''

export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  // Devtools не должны попадать в прод-бандл: значение запекается на этапе
  // сборки, поэтому достаточно проверки NODE_ENV (nuxt build выставляет
  // production). В dev включаем всегда.
  devtools: { enabled: process.env.NODE_ENV !== 'production' },

  // SSR включён (Nuxt SSR через Nitro); для Telegram Mini App можно добавить nitro preset.
  ssr: true,

  modules: [
    '@nuxt/eslint',
    '@nuxtjs/tailwindcss',
    '@pinia/nuxt',
    '@nuxtjs/color-mode',
    'nuxt-icon',
  ],

  // Tailwind подключается через модуль; конфиг в tailwind.config.ts
  css: [
    '~/assets/css/main.css',
    '~/assets/css/landing.css',
  ],

  // pathPrefix: false — UI-примитивы из components/ui/select/ доступны как
  // <Select>/<SelectTrigger>, а не <UiSelectSelect*> (модель shadcn-vue)
  components: [
    // Keep the existing unprefixed shadcn-style names (Button, Dialog, ...).
    { path: '~/components', pathPrefix: false },
    // Also register UI primitives with their explicit Ui* aliases. Using an
    // explicit prefix avoids the scanner deduplicating this directory when
    // the parent components path is registered without prefixes.
    { path: '~/components/ui', prefix: 'Ui' },
  ],

  colorMode: {
    preference: 'light',
    fallback: 'light',
    classSuffix: '',
    // Trade starts from light and must not inherit a legacy dark preference.
    storageKey: 'trade-theme',
  },

  runtimeConfig: {
    // server-only
    apiBase: process.env.API_INTERNAL_BASE || 'http://api:8000',
    // public (доступно на клиенте)
    public: {
      // '' => относительные запросы через nginx (единый вход, §14)
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? 'http://localhost:8000',
      // Хосты, с которых разрешено грузить внешние фото (useProductPhoto).
      // Пусто = никакие: всё отдаётся через /api/v1/files/photo. Список нужен
      // только если в каталоге появятся photo_key с чужим доменом.
      imageAllowedHosts: (process.env.NUXT_PUBLIC_IMAGE_ALLOWED_HOSTS ?? '')
        .split(',')
        .map(host => host.trim().toLowerCase())
        .filter(Boolean),
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'ru' },
      title: 'Клиентский портал',
      titleTemplate: '%s — Клиентский портал',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'description', content: 'B2B-портал «Свет в доме»: каталог светотехники и электромонтажа, персональные цены по договору, заявки онлайн для юридических лиц и ИП.' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
        // Яндекс.Метрика: подключается только если задан NUXT_PUBLIC_METRIKA_ID.
        // ID подставляется в innerHTML тела скрипта, поэтому проверяем, что это
        // именно счётчик (только цифры) — иначе значение из окружения станет
        // исполняемым JS на каждой странице. Нецифровой ID → счётчик не ставится.
        ...(METRIKA_ID
          ? [{
              innerHTML: `(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym(${METRIKA_ID},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});`,
              tagPosition: 'bodyClose' as const,
            }]
          : []),
    },
  },

  typescript: {
    strict: true,
    shim: false,
  },

  experimental: {
    // Отключаем appManifest: виртуальный модуль #app-manifest периодически не
    // разрешается в dev-режиме (флакающий 500 на холодном старте). Эта фича
    // отвечает за клиентский префетч payload'ов роутов — для портала несущественна.
    appManifest: false,
  },

  // Только для `nuxt dev`: при NUXT_PUBLIC_API_BASE="" клиент шлёт запросы в
  // тот же origin, а на хосте их некому принять (в docker это делает nginx из
  // docker-compose). Проксируем /api на локальный API, иначе локальный стенд
  // отдаёт 404 и вход в кабинет невозможен. В production-сборку vite не входит.
  vite: {
    server: {
      proxy: {
        '/api': {
          target: process.env.API_INTERNAL_BASE || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  },

  // Глобальные middleware (см. SITEMAP §1)
  // routeRules — ISR/кэширование по мере необходимости
})
