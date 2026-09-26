<script setup lang="ts">
// Плотный список товаров для служебной панели менеджера.
// Данные приходят из GET /api/v1/dashboard (new_arrivals / promos).
interface ProductCarouselItem {
  id: string
  sku: string
  name: string
  photo_key: string | null
  client_price: string
  currency: string
  has_discount: boolean
}

const props = defineProps<{
  title: string
  icon: string
  items: ProductCarouselItem[]
  itemLink?: (item: ProductCarouselItem) => string
}>()

const { thumbOf } = useProductPhoto()
const sectionId = computed(() => `product-record-${props.title.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, '-').replace(/^-|-$/g, '')}`)
</script>

<template>
  <section class="border border-border bg-surface" :aria-labelledby="sectionId">
    <header class="flex min-h-12 items-center justify-between gap-3 border-b border-border bg-surface-2 px-4 py-2">
      <h3 :id="sectionId" class="flex min-w-0 items-center gap-2 text-sm font-bold text-ink">
        <Icon :name="icon" class="size-5 shrink-0 text-action" aria-hidden="true" />
        <span class="truncate">{{ title }}</span>
        <span class="numeric shrink-0 text-xs font-medium text-ink-muted">{{ items.length }}</span>
      </h3>
    </header>

    <div v-if="!items.length" class="px-4 py-6 text-sm text-ink-muted">
      По этому разделу товаров нет.
    </div>

    <div v-else class="divide-y divide-border">
      <NuxtLink
        v-for="p in props.items"
        :key="p.id"
        :to="props.itemLink ? props.itemLink(p) : `/catalog/${encodeURIComponent(p.sku)}`"
        class="group grid min-h-16 grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-action sm:grid-cols-[56px_minmax(0,1fr)_minmax(8rem,auto)]"
      >
        <div class="flex size-12 items-center justify-center overflow-hidden border border-border bg-background sm:size-14">
          <img
            v-if="thumbOf(p.photo_key)"
            :src="thumbOf(p.photo_key)!"
            :alt="p.name"
            class="size-full object-contain"
            loading="lazy"
          >
          <Icon v-else name="heroicons:photo" class="size-5 text-ink-faint" aria-hidden="true" />
        </div>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold text-ink group-hover:text-action">{{ p.name }}</p>
          <p class="numeric mt-1 truncate text-xs text-ink-muted">SKU {{ p.sku }}</p>
        </div>
        <div class="flex flex-col items-end gap-1 text-right sm:min-w-32">
          <span class="numeric whitespace-nowrap text-sm font-bold text-ink">{{ formatMoney(p.client_price, p.currency) }}</span>
          <span v-if="p.has_discount" class="text-xs font-semibold uppercase tracking-wide text-success">Клиентская цена</span>
          <span v-else class="text-xs text-ink-muted">Цена клиента</span>
        </div>
      </NuxtLink>
    </div>
  </section>
</template>
