// server/plugins/strip-powered-by.ts — убирает из ответа `X-Powered-By: Nuxt`.
//
// Заголовок добавляет рендерер Nuxt ПОСЛЕ server-middleware, поэтому снять его
// из middleware нельзя: к его моменту заголовка ещё нет. Хук beforeResponse
// срабатывает последним, когда заголовки ещё не ушли клиенту.
//
// Само по себе раскрытие фреймворка не дыра, но это дешёвый признак для
// сканера и источник лишней информации; убираем.
import { removeResponseHeader } from 'h3'

export default defineNitroPlugin((nitroApp) => {
  nitroApp.hooks.hook('beforeResponse', (event) => {
    removeResponseHeader(event, 'X-Powered-By')
  })
})
