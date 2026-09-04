// Хелпер URL фото товара (§10, §16 п.17). photo_key бывает двух видов:
//  * http(s)-URL — отдаём как есть;
//  * S3-ключ (photos-series/serie-a.webp) — через API-редирект
//    /api/v1/files/photo?key=… (307 на presigned URL, TTL 5 мин).
// Запасной вариант — attributes.photo_url. См. catalog/index.vue, [sku].vue.
const HTTP_RE = /^https?:\/\//i

function photoUrl(value: string): string {
  if (HTTP_RE.test(value)) return value
  return `/api/v1/files/photo?key=${encodeURIComponent(value)}`
}

export function useProductPhoto() {
  function photoOf(p: { photo_key: string | null; attributes?: Record<string, unknown> }): string | null {
    const v = p.photo_key || (p.attributes?.photo_url as string) || null
    return v ? photoUrl(v) : null
  }

  /** Миниатюра для карточек каталога: ключам photos-series/*.webp
   * подставляет суффикс `_thumb` (конвенция §16 п.17), остальное — как есть. */
  function thumbOf(key: string | null | undefined): string | null {
    if (!key) return null
    const v = key.endsWith('.webp') && !key.endsWith('_thumb.webp')
      ? key.replace(/\.webp$/, '_thumb.webp')
      : key
    return photoUrl(v)
  }

  /** Полный URL произвольного ключа (http-URL как есть, S3-ключ — через редирект).
   * Для галереи доп. фото (ProductDetail.photos), где ключ подаётся отдельно. */
  function urlOf(key: string): string {
    return photoUrl(key)
  }

  return { photoOf, thumbOf, urlOf }
}
