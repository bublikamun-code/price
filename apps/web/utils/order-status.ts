import type { OrderStatus } from '~/types/api'

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

export const ORDER_STATUS_META: Record<OrderStatus, { label: string; tone: StatusTone }> = {
  NEW: { label: 'Новая', tone: 'info' },
  IN_PROGRESS: { label: 'В работе', tone: 'info' },
  SHIPPED: { label: 'Отгружена', tone: 'warning' },
  COMPLETED: { label: 'Завершена', tone: 'success' },
  CANCELLED: { label: 'Отменена', tone: 'danger' },
}

export const ORDER_STATUS_TABS: Array<{ value: '' | OrderStatus; label: string }> = [
  { value: '', label: 'Все' },
  { value: 'NEW', label: 'Новые' },
  { value: 'IN_PROGRESS', label: 'В работе' },
  { value: 'SHIPPED', label: 'Отгружены' },
  { value: 'COMPLETED', label: 'Завершены' },
  { value: 'CANCELLED', label: 'Отменены' },
]
