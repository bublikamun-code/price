// Фото строки заявки/корзины. v2-контракт намеренно не несёт медиа
// («internal storage keys must not enter this transport», catalog v2), поэтому
// ключ берём из существующего v1 GET /products/{sku} — там photo_key равен
// фото товара, иначе фото серии, ответ серверно кэшируется.
//
// Кэш общий на модуль и пополняется только на клиенте: на сервере не делаем
// запрос (иначе SSR утащил бы куки конкретного пользователя), а значит нет и
// риска утечки состояния между SSR-запросами. Один артикул в нескольких
// строках заявки запрашивается один раз (in-flight дедупликация).
import type { ProductDetail } from '~/types/api'

const photoBySku = reactive(new Map<string, string | null>())
const inFlight = new Map<string, Promise<void>>()

export function useLinePhoto() {
  const { request } = useApi()
  const { thumbOf } = useProductPhoto()

  async function load(sku: string | null | undefined): Promise<void> {
    if (import.meta.server) return
    const key = sku?.trim()
    if (!key || photoBySku.has(key)) return

    let task = inFlight.get(key)
    if (!task) {
      task = request<ProductDetail>(`/api/v1/catalog/products/${encodeURIComponent(key)}`)
        .then((product) => {
          photoBySku.set(key, product.photo_key ?? product.series?.photo_key ?? null)
        })
        .catch(() => {
          // Фото — необязательное: любой сбой просто оставляет заглушку.
          photoBySku.set(key, null)
        })
        .finally(() => {
          inFlight.delete(key)
        })
      inFlight.set(key, task)
    }
    await task
  }

  /** URL миниатюры для строки; null — фото нет, показать заглушку. */
  function photoFor(sku: string | null | undefined): string | null {
    const key = sku?.trim()
    if (!key) return null
    const photoKey = photoBySku.get(key)
    return photoKey ? thumbOf(photoKey) : null
  }

  return { load, photoFor }
}
