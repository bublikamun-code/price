<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    description?: string
    code?: string | number
    retryLabel?: string
  }>(),
  {
    title: 'Не удалось выполнить действие',
    description: 'Проверьте соединение и повторите попытку.',
    code: undefined,
    retryLabel: 'Повторить',
  },
)
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="border border-danger/50 bg-danger-soft p-4" role="alert">
    <div class="flex items-start gap-3">
      <Icon
        name="heroicons:exclamation-triangle"
        class="mt-0.5 size-5 shrink-0 text-danger-text"
        aria-hidden="true"
      />
      <div class="min-w-0 flex-1">
        <h3 class="text-sm font-bold text-ink">{{ title }}</h3>
        <p class="mt-1 text-sm leading-5 text-ink-muted">{{ description }}</p>
        <p v-if="code" class="numeric mt-2 text-xs text-ink-muted">Код: {{ code }}</p>
        <div v-if="$slots.action || $attrs.onRetry" class="mt-3">
          <slot name="action">
            <UiButton variant="secondary" size="compact" @click="emit('retry')">
              {{ retryLabel }}
            </UiButton>
          </slot>
        </div>
      </div>
    </div>
  </div>
</template>
