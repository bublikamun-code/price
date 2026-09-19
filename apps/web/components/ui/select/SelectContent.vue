<script setup lang="ts">
import {
  SelectContent,
  type SelectContentEmits,
  type SelectContentProps,
  SelectPortal,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectViewport,
  useForwardPropsEmits,
} from 'reka-ui'

const props = withDefaults(defineProps<SelectContentProps>(), {
  position: 'popper',
  sideOffset: 6,
})
const emits = defineEmits<SelectContentEmits>()
const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <SelectPortal>
    <SelectContent
      v-bind="forwarded"
      class="relative z-50 glass rounded-[18px] p-1.5 shadow-xl min-w-[var(--reka-select-trigger-width)] max-h-[var(--reka-select-content-available-height)]"
    >
      <SelectScrollUpButton class="flex items-center justify-center py-1">
        <Icon name="heroicons:chevron-up" class="w-4 h-4 text-ink-faint" />
      </SelectScrollUpButton>
      <SelectViewport>
        <slot />
      </SelectViewport>
      <SelectScrollDownButton class="flex items-center justify-center py-1">
        <Icon name="heroicons:chevron-down" class="w-4 h-4 text-ink-faint" />
      </SelectScrollDownButton>
    </SelectContent>
  </SelectPortal>
</template>
