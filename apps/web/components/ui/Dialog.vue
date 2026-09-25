<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    initialFocus?: HTMLElement | null
    closeOnOverlay?: boolean
  }>(),
  { description: undefined, initialFocus: null, closeOnOverlay: true },
)
const emit = defineEmits<{ 'update:open': [value: boolean]; close: [] }>()
const panel = shallowRef<HTMLElement | null>(null)
const titleId = `trade-dialog-${useId()}`
const descriptionId = `trade-dialog-description-${useId()}`
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
function lockScroll(lock: boolean): void {
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
      lockScroll(true)
      window.addEventListener('keydown', onKeydown)
    } else {
      lockScroll(false)
      window.removeEventListener('keydown', onKeydown)
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  if (import.meta.client && props.open) lockScroll(false)
  if (import.meta.client) window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[70] flex items-center justify-center p-4 sm:p-6">
      <div
        class="absolute inset-0 bg-ink/60"
        aria-hidden="true"
        @click="closeOnOverlay && close()"
      />
      <section
        ref="panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="description || $slots.description ? descriptionId : undefined"
        tabindex="-1"
        class="relative max-h-[calc(100dvh-2rem)] w-full max-w-xl overflow-y-auto rounded-dialog border border-border-strong bg-surface p-5 shadow-overlay sm:p-6"
      >
        <header class="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 :id="titleId" class="text-xl font-bold leading-7 text-ink">
              {{ title }}
            </h2>
            <p v-if="description" :id="descriptionId" class="mt-1 text-sm leading-5 text-ink-muted">
              {{ description }}
            </p>
            <div
              v-else-if="$slots.description"
              :id="descriptionId"
              class="mt-1 text-sm leading-5 text-ink-muted"
            >
              <slot name="description" />
            </div>
          </div>
          <UiIconButton label="Закрыть" size="touch" variant="ghost" @click="close">
            <Icon name="heroicons:x-mark" class="size-5" aria-hidden="true" />
          </UiIconButton>
        </header>
        <slot />
        <footer
          v-if="$slots.footer"
          class="mt-6 flex flex-wrap justify-end gap-2 border-t border-border pt-4"
        >
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>
