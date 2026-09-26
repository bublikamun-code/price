// server/routes/sitemap.xml.ts — динамическая sitemap.xml (Nitro route).
// Статические страницы + /brands/{slug} из публичного API; кэш 24 ч.
import { SITE_URL } from '../../utils/site'

const CACHE_TTL_MS = 24 * 60 * 60 * 60 * 1000

let cache: { xml: string; createdAt: number } | null = null

const STATIC_PATHS = ['/', '/brands', '/privacy']

function escapeXml(value: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&apos;',
  }
  // Управляющие символы, которые XML 1.0 не допускает, вырезаем: экранировать
  // их нечем, а попав в документ, они делают его невалидным для поисковика.
  return value
    // eslint-disable-next-line no-control-regex -- вычищаем именно эти символы
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '')
    .replace(/[&<>"']/g, ch => map[ch] ?? ch)
}

interface PublicBrand {
  slug?: string | null
}

export default defineEventHandler(async (event) => {
  if (cache && Date.now() - cache.createdAt < CACHE_TTL_MS) {
    setHeader(event, 'Content-Type', 'application/xml; charset=utf-8')
    return cache.xml
  }

  const paths = [...STATIC_PATHS]
  try {
    const apiBase = useRuntimeConfig(event).apiBase
    const res = await $fetch<PublicBrand[] | { data?: PublicBrand[] }>(
      `${apiBase}/api/v1/public/brands`,
      { method: 'GET', timeout: 5000 },
    )
    const brands = Array.isArray(res) ? res : (res.data ?? [])
    for (const b of brands) {
      // slug из данных идёт в путь sitemap'а: оставляем только ожидаемый
      // формат, иначе значение может выйти за пределы сегмента.
      const slug = b?.slug
      if (slug && /^[A-Za-z0-9._-]{1,120}$/.test(slug)) {
        paths.push(`/brands/${slug}`)
      }
    }
  } catch {
    // бренды недоступны — отдаём sitemap со статическими путями
  }

  // Origin берём из константы, а не из Host/X-Forwarded-Host: кэш выше общий
  // на все запросы и живёт 24 часа, поэтому один запрос с подменённым Host
  // зафиксировал бы чужой домен во всём sitemap'е на сутки.
  const origin = SITE_URL
  const urls = paths
    .map((p) => `  <url>\n    <loc>${escapeXml(`${origin}${p}`)}</loc>\n  </url>`)
    .join('\n')
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`
  cache = { xml, createdAt: Date.now() }
  setHeader(event, 'Content-Type', 'application/xml; charset=utf-8')
  return xml
})
