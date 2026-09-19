<script setup lang="ts">
import { SelectTrigger, type SelectTriggerProps, useForwardProps } from 'reka-ui'

const props = defineProps<SelectTriggerProps>()
const forwarded = useForwardProps(props)
</script>

<template>
  <SelectTrigger
    v-bind="forwarded"
    class="input w-full cursor-pointer text-left flex items-center justify-between gap-2 [&>span]:truncate [&[data-state=open]>svg]:rotate-180"
  >
    <slot />
    <Icon name="heroicons:chevron-down" class="w-4 h-4 shrink-0 text-ink-faint transition-transform" />
  </SelectTrigger>
</template>
