<script setup lang="ts">
// Диалог показа временного пароля (создание клиента / сброс пароля, этап 8).
// Пароль выдаётся один раз — бэкенд его не хранит в открытом виде.
const props = defineProps<{ password: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const overlayDown = ref(false)
const dialog = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
let previousOverflow = ''

const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function copy() {
  try {
    await navigator.clipboard.writeText(props.password)
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => (copied.value = false), 2000)
  } catch {
    // clipboard недоступен (нет HTTPS/права) — пароль остаётся видимым для ручного копирования
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return

  // Фокус не должен покинуть модалку ни по Tab, ни по Shift+Tab.
  const focusable = Array.from(dialog.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter(el => !el.hasAttribute('hidden') && el.offsetParent !== null)
  if (!focusable.length) {
    event.preventDefault()
    dialog.value.focus()
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

onMounted(() => {
  previousFocus = document.activeElement as HTMLElement | null
  previousOverflow = document.body.style.overflow
  // Модалка блокирует прокрутку фона, пока пользователь работает с паролем.
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', onKeydown)
  nextTick(() => closeButton.value?.focus())
})

onUnmounted(() => {
  if (copiedTimer) clearTimeout(copiedTimer)
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = previousOverflow
  // Возвращаем клавиатуру на элемент, который открыл диалог.
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-4"
    @mousedown.self="overlayDown = true" @click.self="if (overlayDown) emit('close'); overlayDown = false"
  >
    <div
      ref="dialog"
      class="w-full max-w-md border border-border-strong bg-surface p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="temp-password-title"
      tabindex="-1"
    >
      <div class="flex items-start justify-between gap-4 mb-4">
        <h3 id="temp-password-title" class="font-semibold">Временный пароль</h3>
        <button ref="closeButton" type="button" class="btn-ghost -mr-2 size-11 shrink-0" aria-label="Закрыть" @click="emit('close')">
          <Icon name="heroicons:x-mark" class="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      <div class="badge-warning mb-4">
        <Icon name="heroicons:exclamation-triangle" class="w-4 h-4" />
        Пароль показывается только один раз
      </div>
      <p class="text-sm text-ink-muted mb-4">
        Передайте пароль клиенту для входа в портал. После входа его можно будет сменить.
      </p>

      <div class="flex items-center gap-3 mb-5">
        <code class="min-h-11 flex-1 px-4 py-3 bg-canvas border border-border font-mono text-base break-all select-all">{{ password }}</code>
        <button class="btn-secondary min-h-11 shrink-0" @click="copy">
          <Icon :name="copied ? 'heroicons:check' : 'heroicons:clipboard-document'" class="w-4 h-4" />
          {{ copied ? 'Скопировано' : 'Копировать' }}
        </button>
      </div>

      <button class="btn-primary min-h-11 w-full" @click="emit('close')">Готово</button>
    </div>
  </div>
</template>
