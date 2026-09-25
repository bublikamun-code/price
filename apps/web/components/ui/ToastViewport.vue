<script setup lang="ts">
const { toasts, remove } = useToast()
const { navLayerHeight, stickyLayerHeight } = useBottomLayers()

// Toasts clear whichever bottom lanes are currently mounted.
const laneStyle = computed(() => ({
  bottom: `calc(${navLayerHeight.value}px + ${stickyLayerHeight.value}px + 0.75rem + env(safe-area-inset-bottom, 0px))`,
}))

const toneClasses = {
  info: 'border-info/50 bg-surface',
  success: 'border-success/60 bg-surface',
  error: 'border-danger bg-danger-soft',
} as const
const iconNames = {
  info: 'heroicons:information-circle',
  success: 'heroicons:check-circle',
  error: 'heroicons:exclamation-triangle',
} as const
</script>

<template>
  <div
    class="pointer-events-none fixed inset-x-3 z-[80] flex flex-col items-end gap-2 sm:inset-x-auto sm:right-4 sm:w-96"
    :style="laneStyle"
    role="region"
    aria-label="Уведомления"
    aria-live="polite"
    aria-relevant="additions text"
  >
    <div
      v-for="toast in toasts"
      :key="toast.id"
      :role="toast.type === 'error' ? 'alert' : 'status'"
      class="pointer-events-auto flex w-full items-start gap-2 border p-3 shadow-overlay"
      :class="toneClasses[toast.type]"
    >
      <Icon
        :name="iconNames[toast.type]"
        class="mt-0.5 size-5 shrink-0"
        :class="
          toast.type === 'error'
            ? 'text-danger-text'
            : toast.type === 'success'
              ? 'text-success-text'
              : 'text-info'
        "
        aria-hidden="true"
      />
      <p class="min-w-0 flex-1 text-sm leading-5 text-ink">
        {{ toast.message }}
      </p>
      <NuxtLink
        v-if="toast.action"
        :to="toast.action.to"
        class="shrink-0 text-sm font-semibold text-action hover:underline"
        @click="remove(toast.id)"
      >
        {{ toast.action.label }}
      </NuxtLink>
      <UiIconButton
        label="Закрыть уведомление"
        size="compact"
        variant="ghost"
        @click="remove(toast.id)"
      >
        <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />
      </UiIconButton>
    </div>
  </div>
</template>
