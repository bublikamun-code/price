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
  // немодальный режим: без блокировки прокрутки страницы — иначе при
  // открытии «моргает» экран и пропадает прилипшая пагинация (аудит UX 19.09)
  modal: false,
})
const emits = defineEmits<SelectContentEmits>()
const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <SelectPortal>
    <SelectContent
      v-bind="forwarded"
      class="relative z-50 glass rounded-[16px] p-1 shadow-lg min-w-[160px] max-w-[280px]"
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
