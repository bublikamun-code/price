// Хелпер URL фото товара. photo_key трактуется как готовый URL,
// запасной вариант — attributes.photo_url. См. catalog.vue.
export function useProductPhoto() {
  function photoOf(p: { photo_key: string | null; attributes?: Record<string, unknown> }): string | null {
    return p.photo_key || (p.attributes?.photo_url as string) || null
  }

  return { photoOf }
}
