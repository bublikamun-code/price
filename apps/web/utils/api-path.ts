// Префикс публикации для URL, которые собираются мимо $fetch.
//
// Обычные запросы идут через $fetch/$api — там базовый путь подставляет
// ofetch (baseURL из runtimeConfig.public.apiBase). Но есть места, где URL
// собирается строкой и уходит в браузер напрямую:
//   * <img src="..."> — фото товара и витрины;
//   * new EventSource(...) — SSE-стрим уведомлений;
// такие строки ofetch не трогает, и при публикации под префиксом (например
// /price) они ушли бы в корень домена, где живёт другое приложение.
//
// Хелпер добавляет тот же префикс, что и baseURL, и ничего не меняет на
// обычном стенде (apiBase пустой → путь возвращается как есть).
//
// Базовый путь лучше передавать явно (аргументом): useRuntimeConfig() вне
// контекста Nuxt бросает исключение, а вызовы бывают и в колбэках, где
// контекста уже нет. Без явного base пробуем конфиг и при неудаче оставляем
// путь без префикса.
export function apiPath(path: string, base?: string): string {
  let prefix: string
  if (base !== undefined) {
    prefix = base
  } else {
    try {
      prefix = useRuntimeConfig().public.apiBase
    } catch {
      prefix = ''
    }
  }
  // Пусто (обычный стенд) или абсолютный URL (другой origin) — не трогаем.
  if (!prefix || /^https?:\/\//i.test(prefix)) return path
  const normalized = prefix.replace(/\/+$/, '')
  return path.startsWith('/') ? `${normalized}${path}` : `${normalized}/${path}`
}
