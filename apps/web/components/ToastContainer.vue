<script setup lang="ts">
const { toasts, remove } = useToast()
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-50 flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-2"
      role="region"
      aria-label="Уведомления"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <TransitionGroup>
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="pointer-events-auto flex items-start gap-3 border bg-surface p-3"
          :class="{
            'border-l-success border-success/50': toast.type === 'success',
            'border-l-danger border-danger/50': toast.type === 'error',
            'border-l-info border-info/50': toast.type === 'info',
          }"
          :role="toast.type === 'error' ? 'alert' : 'status'"
          aria-atomic="true"
        >
          <Icon
            :name="toast.type === 'success' ? 'heroicons:check-circle' : toast.type === 'error' ? 'heroicons:exclamation-circle' : 'heroicons:information-circle'"
            class="mt-0.5 size-5 shrink-0"
            :class="toast.type === 'error' ? 'text-danger' : toast.type === 'success' ? 'text-success' : 'text-info'"
            aria-hidden="true"
          />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-ink">{{ toast.message }}</p>
            <NuxtLink
              v-if="toast.action"
              :to="toast.action.to"
              class="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-action hover:underline"
              @click="remove(toast.id)"
            >{{ toast.action.label }}</NuxtLink>
          </div>
          <button
            type="button"
            class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center text-ink-muted hover:bg-surface-2 hover:text-ink"
            aria-label="Закрыть уведомление"
            @click="remove(toast.id)"
          >
            <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
