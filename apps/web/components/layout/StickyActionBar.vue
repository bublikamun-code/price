<script setup lang="ts">
withDefaults(
  defineProps<{
    total?: string
    label: string
    to?: string
    disabled?: boolean
    busy?: boolean
    /** id of the form this bar submits; switches the action to a submit button. */
    form?: string
  }>(),
  { total: '', to: '', disabled: false, busy: false, form: '' },
)

const root = shallowRef<HTMLElement | null>(null)
useStickyLayer(root)
</script>

<template>
  <div
    ref="root"
    class="fixed inset-x-0 z-30 border-t border-border bg-surface px-4 py-3 shadow-sticky lg:hidden"
    :style="{ bottom: 'var(--bottom-nav-offset)' }"
  >
    <div class="mx-auto flex max-w-2xl items-center gap-3">
      <div v-if="total" class="min-w-0 flex-1">
        <span class="block text-xs text-ink-muted">Итого</span>
        <strong class="numeric block truncate text-lg font-bold text-ink">{{ total }}</strong>
      </div>
      <NuxtLink
        v-if="to"
        :to="to"
        class="inline-flex min-h-11 flex-1 items-center justify-center gap-2 border border-action bg-action px-4 text-sm font-semibold text-action-on hover:bg-action-hover"
        :class="total ? '' : 'w-full'"
        :aria-disabled="disabled || undefined"
      >
        <UiSpinner v-if="busy" :size="16" />
        <span>{{ label }}</span>
      </NuxtLink>
      <UiButton
        v-else
        size="touch"
        class="flex-1"
        :type="form ? 'submit' : 'button'"
        :form="form || undefined"
        :loading="busy"
        :disabled="disabled"
      >
        {{ label }}
      </UiButton>
    </div>
  </div>
</template>
