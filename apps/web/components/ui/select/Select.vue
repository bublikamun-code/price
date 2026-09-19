<script setup lang="ts">
// UI-примитивы (модель shadcn-vue / reka-ui). Пилот аудита 19.09:
// самописный BaseSelect → примитивы с доступностью (фокус, клавиатура, portal).
import { SelectRoot, type SelectRootEmits, type SelectRootProps, useForwardPropsEmits } from 'reka-ui'

const props = defineProps<SelectRootProps>()
const emits = defineEmits<SelectRootEmits>()
const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <SelectRoot v-bind="forwarded">
    <slot />
  </SelectRoot>
</template>
