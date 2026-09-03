<script setup lang="ts">
// Контейнер тостов: телепорт в body, список через TransitionGroup.
// Источник данных — composables/useToast.ts (toasts, remove).
const { toasts, remove } = useToast()
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed bottom-4 right-4 z-50 flex flex-col gap-3 w-[calc(100vw-2rem)] max-w-sm pointer-events-none"
      aria-live="polite"
      aria-atomic="true"
    >
      <TransitionGroup
        class="contents"
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0 translate-y-3 scale-95"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 translate-x-0"
        leave-to-class="opacity-0 translate-x-6"
        move-class="transition-all duration-300"
      >
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="pointer-events-auto card p-4 shadow-card-hover flex items-start gap-3"
          :class="{
            'border-success/40 bg-success-soft/40': toast.type === 'success',
            'border-danger/40 bg-danger-soft/40': toast.type === 'error',
            'border-primary/40 bg-primary-soft/30': toast.type === 'info',
          }"
        >
          <div class="mt-0.5 shrink-0">
            <Icon v-if="toast.type === 'success'" name="heroicons:check-circle" class="w-5 h-5 text-success" />
            <Icon v-else-if="toast.type === 'error'" name="heroicons:exclamation-circle" class="w-5 h-5 text-danger" />
            <Icon v-else name="heroicons:information-circle" class="w-5 h-5 text-primary" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-ink">{{ toast.message }}</p>
            <div v-if="toast.action" class="mt-2">
              <NuxtLink
                :to="toast.action.to"
                class="text-sm font-semibold text-primary hover:text-primary-hover hover:underline"
                @click="remove(toast.id)"
              >
                {{ toast.action.label }}
              </NuxtLink>
            </div>
          </div>
          <button class="shrink-0 text-ink-faint hover:text-ink transition-colors" aria-label="Закрыть" @click="remove(toast.id)">
            <Icon name="heroicons:x-mark" class="w-4 h-4" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
