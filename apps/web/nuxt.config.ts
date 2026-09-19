// https://nuxt.com/docs/api/configuration/nuxt-config
// См. ARCHITECTURE_PLAN.md §3 (дизайн), SITEMAP.md §1 (роутинг/layouts).
export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  devtools: { enabled: true },

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
  css: ['~/assets/css/main.css'],

  // pathPrefix: false — UI-примитивы из components/ui/select/ доступны как
  // <Select>/<SelectTrigger>, а не <UiSelectSelect*> (модель shadcn-vue)
  components: [{ path: '~/components', pathPrefix: false }],

  colorMode: {
    preference: 'dark',   // новый дизайн — тёмный по умолчанию
    fallback: 'dark',
    classSuffix: '',      // класс `dark` на <html> (селекторы в main.css)
    // Новый ключ: в браузерах пользователей остался старый 'nuxt-color-mode'='light'
    // от прошлого светлого дизайна, он перекрывал дефолт 'dark'. Начинаем чисто.
    storageKey: 'nuxt-color-mode-v2',
  },

  runtimeConfig: {
    // server-only
    apiBase: process.env.API_INTERNAL_BASE || 'http://api:8000',
    // public (доступно на клиенте)
    public: {
      // '' => относительные запросы через nginx (единый вход, §14)
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? 'http://localhost:8000',
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'ru' },
      title: 'Клиентский портал',
      titleTemplate: '%s — Клиентский портал',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'B2B-портал «Свет в доме»: каталог светотехники и электромонтажа, персональные цены по договору, заявки онлайн для юридических лиц и ИП.' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
        // Яндекс.Метрика: подключается только если задан NUXT_PUBLIC_METRIKA_ID
        ...(process.env.NUXT_PUBLIC_METRIKA_ID
          ? [{
              innerHTML: `(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");ym(${process.env.NUXT_PUBLIC_METRIKA_ID},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});`,
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

  // Глобальные middleware (см. SITEMAP §1)
  // routeRules — ISR/caching по мере необходимости
})
