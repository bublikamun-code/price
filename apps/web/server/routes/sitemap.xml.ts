// server/routes/sitemap.xml.ts — динамическая sitemap.xml (Nitro route).
// Статические страницы + /brands/{slug} из публичного API; кэш 24 ч.

const CACHE_TTL_MS = 24 * 60 * 60 * 1000

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
  return value.replace(/[&<>"']/g, (ch) => map[ch] ?? ch)
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
      if (b?.slug) paths.push(`/brands/${b.slug}`)
    }
  } catch {
    // бренды недоступны — отдаём sitemap со статическими путями
  }

  const origin = getRequestURL(event, { xForwardedHost: true, xForwardedProto: true }).origin
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
