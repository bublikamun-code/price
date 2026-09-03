// Аватар-плашка: инициалы компании (или имени) для шапки — автоимпорт Nuxt.

/** Инициалы из названия компании/имени: первые буквы двух первых слов. */
export function getCompanyInitials(company?: string | null, fallbackName?: string | null): string {
  const source = (company || fallbackName || '?').trim()
  if (!source) return '?'
  const words = source.split(/\s+/).filter(Boolean)
  const chars = words.slice(0, 2).map((w) => w.charAt(0).toUpperCase())
  return chars.join('') || source.charAt(0).toUpperCase()
}
