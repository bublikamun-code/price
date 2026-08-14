// ESLint 9 Flat Config для Nuxt 3 + Vue 3 + TypeScript
// Генерируется через @nuxt/eslint (nuxt prepare создаёт .nuxt/eslint.config.mjs).
// Документация: https://eslint.nuxt.com/packages/module

import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  // Дополнительные правила проекта
  {
    rules: {
      // Разрешаем console.log в dev-коде (убрать при необходимости)
      'no-console': 'warn',
    },
  },
)
