import type { OrderApprovalStatus, OrderStatus } from '~/types/api'

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

// Согласование владельцем (Э6): показываем только PENDING/REJECTED —
// APPROVED и NOT_REQUIRED в списках не отображаем, чтобы не шуметь.
export const ORDER_APPROVAL_META: Record<'PENDING' | 'REJECTED', { label: string; tone: StatusTone }> = {
  PENDING: { label: 'Ждёт согласования', tone: 'warning' },
  REJECTED: { label: 'Отклонена', tone: 'danger' },
}

export function orderApprovalBadge(
  status: OrderApprovalStatus | null | undefined,
): { label: string; tone: StatusTone } | null {
  if (status === 'PENDING' || status === 'REJECTED') return ORDER_APPROVAL_META[status]
  return null
}
