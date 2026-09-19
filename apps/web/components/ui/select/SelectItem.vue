<script setup lang="ts">
import { SelectItem, SelectItemIndicator, SelectItemText, type SelectItemProps, useForwardProps } from 'reka-ui'

const props = defineProps<SelectItemProps>()
const forwarded = useForwardProps(props)
</script>

<template>
  <SelectItem
    v-bind="forwarded"
    class="w-full cursor-pointer select-none rounded-[12px] px-2.5 py-1.5 text-sm text-ink whitespace-nowrap outline-none transition-colors flex items-center justify-between gap-2 data-[highlighted]:bg-surface-2 data-[state=checked]:bg-ink/5 data-[state=checked]:font-semibold"
  >
    <SelectItemText><slot /></SelectItemText>
    <SelectItemIndicator as-child>
      <Icon name="heroicons:check" class="w-4 h-4 shrink-0 text-primary" />
    </SelectItemIndicator>
  </SelectItem>
</template>
