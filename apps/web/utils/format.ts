// Утилиты форматирования — автоимпорт Nuxt
// Сигнатуры и поведение — как в прод-билде (чанк format-*.mjs)

const moneyFormatter = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatMoney(value: number | string, currency?: string): string {
  const n = typeof value === 'string' ? Number.parseFloat(value) : value
  const safe = Number.isFinite(n) ? n : 0
  const formatted = moneyFormatter.format(safe)
  return currency ? `${formatted} ${currency}` : formatted
}

export function formatPercent(value: number | string): string {
  const n = typeof value === 'string' ? Number.parseFloat(value) : value
  if (!Number.isFinite(n)) return '—'
  const rounded = Math.round(n * 10) / 10
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1).replace('.', ',')
  return `${text}%`
}

export function pluralize(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(n) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return many
  if (last > 1 && last < 5) return few
  if (last === 1) return one
  return many
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return '—'
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${dd}.${mm}.${yyyy}, ${hh}:${mi}`
}

export function formatDate(value: string | Date | null | undefined): string {
  return formatDateTime(value).split(',')[0] ?? '—'
}

export function formatOrderNumber(seq: number | null | undefined, id: string): string {
  if (seq != null) return `З-${String(seq).padStart(6, '0')}`
  return `№${id.slice(0, 8)}`
}
