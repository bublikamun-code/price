// Глобальные toast-уведомления (ToastContainer.vue рендерит `toasts`).
// Состояние — на уровне модуля: один стек на всё приложение.

export type ToastType = 'info' | 'success' | 'error'

export interface ToastAction {
  label: string
  to: string
}

export interface Toast {
  id: string
  message: string
  type: ToastType
  /** мс; 0 — не скрывать автоматически */
  duration: number
  action: ToastAction | null
}

export interface ToastOptions {
  type?: ToastType
  duration?: number
  action?: ToastAction | null
}

const toasts = ref<Toast[]>([])
let idCounter = 0

export function useToast() {
  function show(message: string, opts: ToastOptions = {}): Toast {
    const id = `${Date.now()}-${++idCounter}`
    const toast: Toast = {
      id,
      message,
      type: opts.type ?? 'info',
      duration: opts.duration ?? 4000,
      action: opts.action ?? null,
    }
    toasts.value.push(toast)
    if (toast.duration > 0) {
      setTimeout(() => remove(id), toast.duration)
    }
    return toast
  }

  function success(message: string, opts: ToastOptions = {}): Toast {
    return show(message, { type: 'success', duration: opts.duration, action: opts.action })
  }

  function error(message: string, opts: ToastOptions = {}): Toast {
    return show(message, { type: 'error', duration: opts.duration, action: opts.action })
  }

  function remove(id: string): void {
    const idx = toasts.value.findIndex((t) => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  return { toasts, show, success, error, remove }
}
