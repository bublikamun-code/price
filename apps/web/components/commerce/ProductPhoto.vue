<script setup lang="ts">
import type { CatalogMediaResource } from '~/domain/api/v2/catalog.schema'

// Кадр товара из v2-контракта (§16 п.37). Раньше карточка каталога и страница
// товара держали заглушку «Фото товара пока недоступно» безусловно, хотя API уже
// отдаёт thumbnail.
//
// URL стабильный (`/api/v2/media/{id}` отдаёт байты), поэтому картинку
// можно отдавать с иммутабельным кэшем. Сорванная загрузка — удалённый ключ
// или недоступный бакет — не должна оставлять дыру, поэтому при ошибке
// показываем иконку, а не битую картинку.
const props = withDefaults(
  defineProps<{
    media?: CatalogMediaResource | null
    alt: string
    /** object-contain для крупного кадра, object-cover для плитки. */
    fit?: 'cover' | 'contain'
    eager?: boolean
  }>(),
  { media: null, fit: 'cover', eager: false },
)

const failed = ref(false)
// Новый товар в том же списке переиспользует компонент: сброс ошибки по смене
// id, иначе иконка залипла бы на всём следующем кадре.
watch(
  () => props.media?.id,
  () => {
    failed.value = false
  },
)
const src = computed(() => (failed.value ? null : props.media?.url ?? null))
</script>

<template>
  <div class="relative flex items-center justify-center overflow-hidden bg-surface-2">
    <img
      v-if="src"
      :src="src"
      :alt="alt"
      :width="media?.width"
      :height="media?.height"
      class="size-full"
      :class="fit === 'contain' ? 'object-contain' : 'object-cover'"
      :loading="eager ? 'eager' : 'lazy'"
      decoding="async"
      data-testid="product-photo"
      @error="failed = true"
    >
    <Icon v-else name="heroicons:photo" class="size-7 text-ink-faint" aria-hidden="true" />
  </div>
</template>
