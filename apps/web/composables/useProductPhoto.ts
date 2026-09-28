// Хелпер URL фото товара (§10, §16 п.17). photo_key бывает двух видов:
//  * http(s)-URL — отдаём как есть, но только для хостов из allowlist;
//  * S3-ключ (photos-series/serie-a.webp) — через /api/v1/files/photo?key=…,
//    который отдаёт байты изображения (200). Раньше был 307 на presigned, но
//    внешний S3-хост живёт по http, и https-браузер резал фото как mixed content.
// Запасной вариант — attributes.photo_url. См. catalog/index.vue, [sku].vue.
//
// Про внешние URL: photo_key приходит из данных каталога, то есть из
// импортированной выгрузки поставщика, и раньше подставлялся в <img src> как
// есть. Это позволяло подсунуть в каталог картинку с любого домена — вплоть до
// маячка, отслеживающего открытие страницы конкретным пользователем. Поэтому
// http(s)-URL проходит только если его хост перечислен в
// NUXT_PUBLIC_IMAGE_ALLOWED_HOSTS; всё прочее отбрасывается (null → иконка).
// По умолчанию список пуст: в проде внешних фото в данных нет, галереи
// загружены в S3, а photo_url с files.keaz.ru есть лишь как запасной вариант
// у товаров, у которых уже есть свой photo_key.
const HTTP_RE = /^https?:\/\//i

function allowedExternalUrl(value: string): string | null {
  let host: string
  try {
    host = new URL(value).host.toLowerCase()
  } catch {
    return null
  }
  const allowed = useRuntimeConfig().public.imageAllowedHosts
  return allowed.includes(host) ? value : null
}

function photoUrl(value: string): string | null {
  if (HTTP_RE.test(value)) return allowedExternalUrl(value)
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

  /** Полный URL произвольного ключа (http-URL — только из allowlist, S3-ключ —
   * через API с байтами). Для галереи доп. фото (ProductDetail.photos), где ключ
   * подаётся отдельно. */
  function urlOf(key: string | null | undefined): string | null {
    return key ? photoUrl(key) : null
  }

  return { photoOf, thumbOf, urlOf }
}
