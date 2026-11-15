// Выбор источника изображения для главного кадра карточки.
//
// Аудит L13: мобильная карточка грузила крупный кадр 1200×1200, хотя в
// мобильном боксе он всё равно не виден. По конвенции проекта (§16 п.17)
// рядом с кадром лежит миниатюра 400×400 (`_thumb.webp`), и в v2-контракте —
// URL с `?size=thumb`. Здесь решается одно: какой URL показать.
//
// Правила:
//  * по умолчанию — миниатюра;
//  * если миниатюра уже падала (битый ключ/недоступный бакет) — откат на
//    полный кадр;
//  * если не грузится ни то, ни другое — null: страница рисует заглушку.
//
// Хелпер чистый: логику можно покрыть обычным vitest-тестом без Nuxt.
export interface PhotoFrameUrls {
  /** Полный кадр. */
  url: string
  /** Миниатюра 400×400. */
  thumbUrl: string
}

/**
 * URL главного кадра.
 *
 * @param frame кадр (null — фото нет)
 * @param failed URL'ы, которые уже не загрузились
 */
export function mainPhotoSrc(
  frame: PhotoFrameUrls | null | undefined,
  failed: ReadonlySet<string>,
): string | null {
  if (!frame) return null
  if (frame.thumbUrl === frame.url) return failed.has(frame.url) ? null : frame.url
  if (!failed.has(frame.thumbUrl)) return frame.thumbUrl
  if (!failed.has(frame.url)) return frame.url
  return null
}
