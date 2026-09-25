// server/routes/robots.txt.ts — robots.txt как Nitro-route (§16 п.29).
// Динамический вместо статики: Sitemap требует абсолютный URL, а хост
// известен только на запросе (деплой может перезжать между доменами).
// Приватные зоны закрыты и noindex-метами в layout'ах — это второй барьер.
const PRIVATE_PREFIXES = [
  '/manager',
  '/m/',
  '/cart',
  '/checkout',
  '/orders',
  '/favorites',
  '/profile',
  '/notifications',
  '/files',
  '/dashboard',
  '/analytics',
  '/bulk-add',
  '/force-change-password',
  '/reset-password',
  '/login',
  '/api/',
]

export default defineEventHandler((event) => {
  const url = getRequestURL(event)
  const base = `${url.protocol}//${url.host}`
  setHeader(event, 'Content-Type', 'text/plain; charset=utf-8')
  return [
    'User-agent: *',
    'Allow: /',
    ...PRIVATE_PREFIXES.map((p) => `Disallow: ${p}`),
    'Crawl-delay: 0.5',
    '',
    `Sitemap: ${base}/sitemap.xml`,
    '',
  ].join('\n')
})
