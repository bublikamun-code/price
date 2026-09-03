// Утилиты для отображения атрибутов товаров — автоимпорт Nuxt.
// Маппинг ключей характеристик на человекочитаемые подписи/единицы (каталог, §6).

const ATTRIBUTE_LABELS: Record<string, string> = {
  // Основные электротехнические характеристики
  power_va: 'Мощность, ВА',
  power: 'Мощность, ВА',
  execution: 'Исполнение',
  input_voltage: 'Входное напряжение, В',
  output_voltage: 'Выходное напряжение, В',
  voltage: 'Напряжение, В',
  voltage_range: 'Диапазон напряжения, В',
  current: 'Ток, А',
  current_a: 'Ток, А',
  frequency: 'Частота, Гц',
  efficiency: 'КПД, %',
  // Габариты и вес
  dimensions: 'Габариты, мм',
  dimensions_mm: 'Габариты, мм',
  dims: 'Размеры, мм',
  length: 'Длина, мм',
  width: 'Ширина, мм',
  width_mm: 'Ширина, мм',
  height: 'Высота, мм',
  height_mm: 'Высота, мм',
  depth: 'Глубина, мм',
  depth_mm: 'Глубина, мм',
  product_width_mm: 'Ширина изделия, мм',
  product_height_mm: 'Высота изделия, мм',
  product_depth_mm: 'Глубина изделия, мм',
  size: 'Размер',
  weight: 'Вес, кг',
  weight_g: 'Вес, г',
  // Защита / климат
  protection_degree: 'Степень защиты, IP',
  ip_rating: 'Степень защиты, IP',
  ip: 'Класс защиты (IP)',
  ik_rating: 'Ударная прочность IK',
  ik: 'Класс защиты (IK)',
  temperature: 'Температура эксплуатации, °C',
  temperature_range: 'Рабочая температура, °C',
  climate: 'Климатическое исполнение',
  electric_protection: 'Степень защиты от поражения эл. током',
  // Комплектация / монтаж
  modules: 'Модули',
  din_modules: 'Количество модулей DIN',
  rows: 'Количество рядов',
  mounting_type: 'Тип монтажа',
  mounting: 'Монтаж',
  mounting_plate: 'Монтажная плата',
  wall_mount: 'Настенный монтаж',
  floor_mount: 'Напольный монтаж',
  outdoor: 'Установка вне помещений',
  // Общие
  article: 'Артикул',
  sku: 'Артикул',
  brand: 'Бренд',
  series: 'Серия',
  series_short: 'Серия',
  model: 'Модель',
  type: 'Тип',
  material: 'Материал',
  color: 'Цвет',
  door_color: 'Цвет дверцы',
  purpose: 'Назначение',
  standard: 'Стандарт',
  country: 'Страна производства',
  brand_country: 'Страна бренда',
  certificate: 'Сертификат',
  warranty: 'Гарантия, мес',
  warranty_months: 'Гарантия, мес',
  package_qty: 'Упаковка, шт',
  unit: 'Ед. измерения',
  acceptance: 'Тип приёмки',
  tn_ved_code: 'Код ТН ВЭД',
}

const ATTRIBUTE_UNITS: Record<string, string> = {
  power_va: 'ВА',
  power: 'ВА',
  weight: 'кг',
  weight_g: 'г',
  dimensions: 'мм',
  dimensions_mm: 'мм',
  dims: 'мм',
  length: 'мм',
  width: 'мм',
  width_mm: 'мм',
  height: 'мм',
  height_mm: 'мм',
  depth: 'мм',
  depth_mm: 'мм',
  product_width_mm: 'мм',
  product_height_mm: 'мм',
  product_depth_mm: 'мм',
  current: 'А',
  current_a: 'А',
  frequency: 'Гц',
  efficiency: '%',
  protection_degree: 'IP',
  ip_rating: 'IP',
  temperature: '°C',
  temperature_range: '°C',
  warranty: 'мес',
  warranty_months: 'мес',
  voltage: 'В',
  input_voltage: 'В',
  output_voltage: 'В',
  voltage_range: 'В',
  package_qty: 'шт',
}

/** Служебные ключи атрибутов: не выводим как характеристики (фото/описание). */
export const SERVICE_ATTR_KEYS = new Set(['photo_url', 'photo2_url', 'photos', 'description'])

/** "some_key" → "Some key". */
function humanizeKey(key: string): string {
  const s = key.replaceAll('_', ' ').trim()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : key
}

/** Человекочитаемая подпись характеристики; неизвестный ключ — humanize. */
export function getAttributeLabel(key: string): string {
  return ATTRIBUTE_LABELS[key] ?? humanizeKey(key)
}

/** Строка содержит только числа/разделители/знаки (можно дописать единицу). */
function isNumericString(value: string): boolean {
  return /^[\d\s,.\-–—+/]+$/.test(value.trim())
}

function formatNumberValue(value: number, unit?: string): string {
  if (unit) return `${value} ${unit}`
  return String(value)
}

/** Габариты: массив/объект {length,width,height,depth} → "a × b × c мм". */
function formatDimensions(value: unknown): string {
  if (Array.isArray(value)) {
    const parts = value.filter((v) => v != null).map(String)
    return parts.length ? `${parts.join(' × ')} мм` : '—'
  }
  if (value !== null && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const order = ['length', 'width', 'height', 'depth', 'l', 'w', 'h', 'd']
    const parts = order.map((k) => obj[k]).filter((v) => v != null).map(String)
    if (parts.length) return `${parts.join(' × ')} мм`
  }
  return value === null || value === undefined ? '—' : String(value)
}

/** Отформатированное значение характеристики для вывода в карточке товара. */
export function formatAttributeValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (key === 'dimensions' || key === 'dimensions_mm') {
    return formatDimensions(value)
  }
  const unit = ATTRIBUTE_UNITS[key]
  if (typeof value === 'number') {
    return formatNumberValue(value, unit)
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return '—'
    if (!unit) return trimmed
    if (trimmed.includes(unit)) return trimmed
    if (isNumericString(trimmed)) return `${trimmed} ${unit}`
    return trimmed
  }
  return String(value)
}
