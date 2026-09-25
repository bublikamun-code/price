import type { MaybeRefOrGetter } from 'vue'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function resolve(value: MaybeRefOrGetter<HTMLElement | null | undefined>) {
  return toValue(value)
}

export function useFocusTrap(
  container: MaybeRefOrGetter<HTMLElement | null | undefined>,
  active: MaybeRefOrGetter<boolean>,
  options: {
    autoFocus?: boolean
    initialFocus?: MaybeRefOrGetter<HTMLElement | null | undefined>
  } = {},
) {
  let previousFocus: HTMLElement | null = null
  let listeningDocument: Document | null = null

  function focusableElements(): HTMLElement[] {
    const element = resolve(container)
    if (!element) return []
    return Array.from(element.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (candidate) => !candidate.hidden && candidate.getAttribute('aria-hidden') !== 'true',
    )
  }

  function focusInitial(): void {
    const requested = options.initialFocus ? resolve(options.initialFocus) : null
    const first = focusableElements()[0]
    const target = requested ?? (options.autoFocus === false ? null : first)
    target?.focus({ preventScroll: true })
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Tab') return
    const focusable = focusableElements()
    const containerElement = resolve(container)
    if (!focusable.length || !containerElement) {
      event.preventDefault()
      containerElement?.focus({ preventScroll: true })
      return
    }

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const current = document.activeElement as HTMLElement | null

    if (event.shiftKey && (current === first || !containerElement.contains(current))) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && current === last) {
      event.preventDefault()
      first?.focus()
    }
  }

  function onFocusIn(event: FocusEvent): void {
    const containerElement = resolve(container)
    if (containerElement && !containerElement.contains(event.target as Node)) {
      const target = focusableElements()[0] ?? containerElement
      target.focus({ preventScroll: true })
    }
  }

  function activate(): void {
    if (!import.meta.client || listeningDocument) return
    const element = resolve(container)
    if (!element) {
      nextTick(() => {
        if (toValue(active) && resolve(container)) activate()
      })
      return
    }
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    listeningDocument = element.ownerDocument
    listeningDocument.addEventListener('keydown', onKeydown, true)
    listeningDocument.addEventListener('focusin', onFocusIn, true)
    nextTick(focusInitial)
  }

  function deactivate(restoreFocus = true): void {
    listeningDocument?.removeEventListener('keydown', onKeydown, true)
    listeningDocument?.removeEventListener('focusin', onFocusIn, true)
    listeningDocument = null
    if (restoreFocus && previousFocus?.isConnected) {
      previousFocus.focus({ preventScroll: true })
    }
    previousFocus = null
  }

  watch(
    () => toValue(active),
    (isActive) => (isActive ? activate() : deactivate()),
  )
  onMounted(() => {
    if (toValue(active)) activate()
  })
  onScopeDispose(() => deactivate(false))

  return { activate, deactivate }
}
