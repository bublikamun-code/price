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

  colorMode: {
    preference: 'light',
    fallback: 'light',
    classSuffix: '',
  },

  runtimeConfig: {
    // server-only
    apiBase: process.env.API_INTERNAL_BASE || 'http://api:8000',
    // public (доступно на клиенте)
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000',
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
        { name: 'description', content: 'B2B-портал с динамическими прайс-листами' },
      ],
      link: [{ rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
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
