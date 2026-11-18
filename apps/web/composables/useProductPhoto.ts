// Хелпер URL фото товара (§10, §16 п.17). photo_key бывает трёх видов:
//  * http(s)-URL — отдаём как есть, но только для хостов из allowlist;
//  * S3-ключ каталога (photos-series/serie-a.webp, photos-product/<id>/<8hex>.webp)
//    — через /api/v1/files/photo?key=…, который отдаёт байты изображения (200).
//    Раньше был 307 на presigned, но внешний S3-хост живёт по http, и
//    https-браузер резал фото как mixed content;
//  * «сырое» имя файла из CSV (serie_a.jpg) — это НЕ ключ в бакете: объекта с
//    таким именем нет, и запрос за ним вернул бы 404 (битая картинка вместо
//    заглушки). Такие значения отсекаются: см. isPhotoKey().
//
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
import { apiPath } from '../utils/api-path'

const HTTP_RE = /^https?:\/\//i

/**
 * Префиксы S3-ключей фото каталога в бакете photos.
 *
 * Ключи фото серий и галерей товаров живут под своими префиксами; всё прочее
 * (баннеры — banners/…) — не фото товара и в этот список не попадает.
 */
const PHOTO_KEY_PREFIXES = ['photos-series/', 'photos-product/']

/** True, если значение — S3-ключ фото каталога (а не «сырое» имя из CSV). */
export function isPhotoKey(value: string | null | undefined): boolean {
  if (!value) return false
  return PHOTO_KEY_PREFIXES.some((prefix) => value.startsWith(prefix))
}

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

function photoUrl(value: string, base: string): string | null {
  if (HTTP_RE.test(value)) return allowedExternalUrl(value)
  // apiPath: при публикации под префиксом (/price) фото должно уходить
  // на <base>/api/..., иначе запрос уйдёт в корень домена (чужое приложение).
  return apiPath(`/api/v1/files/photo?key=${encodeURIComponent(value)}`, base)
}

export function useProductPhoto() {
  // Базовый префикс публикации (пусто на обычном стенде, '/price' — публично).
  const apiBase = useRuntimeConfig().public.apiBase

  function photoOf(p: { photo_key: string | null; attributes?: Record<string, unknown> }): string | null {
    const v = p.photo_key || (p.attributes?.photo_url as string) || null
    if (!v) return null
    if (HTTP_RE.test(v)) return allowedExternalUrl(v)
    return isPhotoKey(v) ? photoUrl(v, apiBase) : null
  }

  /** Миниатюра для карточек каталога: ключам photos-*.webp
   * подставляется суффикс `_thumb` (конвенция §16 п.17), остальное — как есть. */
  function thumbOf(key: string | null | undefined): string | null {
    if (!key || !isPhotoKey(key)) return null
    const v = key.endsWith('.webp') && !key.endsWith('_thumb.webp')
      ? key.replace(/\.webp$/, '_thumb.webp')
      : key
    return photoUrl(v, apiBase)
  }

  /** Полный URL произвольного ключа (http-URL — только из allowlist, S3-ключ —
   * через API с байтами). Для галереи доп. фото (ProductDetail.photos), где ключ
   * подаётся отдельно, и для баннеров (banners/…). */
  function urlOf(key: string | null | undefined): string | null {
    if (!key) return null
    if (HTTP_RE.test(key)) return allowedExternalUrl(key)
    // Ключ без «/» — не путь внутри бакета (такое значение объектом не является).
    return key.includes('/') ? photoUrl(key, apiBase) : null
  }

  return { photoOf, thumbOf, urlOf }
}
