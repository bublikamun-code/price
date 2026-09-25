<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    side?: 'right' | 'left' | 'bottom'
    initialFocus?: HTMLElement | null
  }>(),
  { description: undefined, side: 'right', initialFocus: null },
)
const emit = defineEmits<{ 'update:open': [value: boolean]; close: [] }>()
const panel = shallowRef<HTMLElement | null>(null)
const titleId = `trade-sheet-${useId()}`
const descriptionId = `trade-sheet-description-${useId()}`
let previousOverflow = ''

function close(): void {
  emit('update:open', false)
  emit('close')
}
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}
function setScrollLock(lock: boolean): void {
  if (!import.meta.client) return
  if (lock) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = previousOverflow
  }
}

useFocusTrap(panel, () => props.open, {
  initialFocus: () => props.initialFocus,
})
watch(
  () => props.open,
  (open) => {
    if (!import.meta.client) return
    if (open) {
      setScrollLock(true)
      window.addEventListener('keydown', onKeydown)
    } else {
      setScrollLock(false)
      window.removeEventListener('keydown', onKeydown)
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  if (import.meta.client && props.open) setScrollLock(false)
  if (import.meta.client) window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[70]" @keydown.esc.prevent="close">
      <div class="absolute inset-0 bg-ink/60" aria-hidden="true" @click="close" />
      <section
        ref="panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="description ? descriptionId : undefined"
        tabindex="-1"
        class="absolute flex flex-col border-border-strong bg-surface shadow-overlay"
        :class="{
          'inset-x-0 bottom-0 max-h-[92dvh] border-t pb-[max(1rem,env(safe-area-inset-bottom))]':
            side === 'bottom',
          'inset-y-0 right-0 w-[min(92vw,30rem)] border-l': side === 'right',
          'inset-y-0 left-0 w-[min(92vw,30rem)] border-r': side === 'left',
        }"
      >
        <header class="flex items-start justify-between gap-4 border-b border-border p-4">
          <div>
            <h2 :id="titleId" class="text-xl font-bold leading-7 text-ink">
              {{ title }}
            </h2>
            <p v-if="description" :id="descriptionId" class="mt-1 text-sm leading-5 text-ink-muted">
              {{ description }}
            </p>
          </div>
          <UiIconButton label="Закрыть" size="touch" variant="ghost" @click="close">
            <Icon name="heroicons:x-mark" class="size-5" aria-hidden="true" />
          </UiIconButton>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto p-4">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="border-t border-border p-4">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>
