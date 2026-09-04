<script setup lang="ts">
// Горизонтальная карусель карточек товара (dashboard: «Акции», «Новинки»).
// Нативный скролл с snap (на мобильном — свайп) + стрелки scrollBy по ширине видимой зоны.
// Данные: элементы шейпа { id, sku, name, photo_key, client_price, currency, has_discount }
// из GET /api/v1/dashboard (new_arrivals / promos). Клик по карточке → /catalog/[sku]
// (переопределяется пропом itemLink — менеджерский дашборд шлёт на /manager/catalog).
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
const track = ref<HTMLElement | null>(null)

// Прокрутка на ~80% ширины видимой зоны — карточки не «срезаются» на краю.
function scrollByDir(dir: 1 | -1) {
  const el = track.value
  if (!el) return
  el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: 'smooth' })
}
</script>

<template>
  <div class="card overflow-hidden">
    <div class="flex items-center justify-between gap-2 px-6 py-4">
      <h3 class="font-semibold flex items-center gap-2 min-w-0">
        <Icon :name="icon" class="w-5 h-5 shrink-0 text-primary" />
        <span class="truncate">{{ title }}</span>
      </h3>
      <div class="flex items-center gap-1 shrink-0">
        <button
          type="button"
          class="w-8 h-8 rounded-card border border-border flex items-center justify-center text-ink-muted hover:text-primary hover:border-primary transition-colors"
          :aria-label="`Прокрутить ${title} назад`"
          @click="scrollByDir(-1)"
        >
          <Icon name="heroicons:chevron-left" class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="w-8 h-8 rounded-card border border-border flex items-center justify-center text-ink-muted hover:text-primary hover:border-primary transition-colors"
          :aria-label="`Прокрутить ${title} вперёд`"
          @click="scrollByDir(1)"
        >
          <Icon name="heroicons:chevron-right" class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div
      ref="track"
      class="flex gap-3 px-6 pb-6 overflow-x-auto snap-x snap-mandatory [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      <NuxtLink
        v-for="p in props.items"
        :key="p.id"
        :to="props.itemLink ? props.itemLink(p) : `/catalog/${p.sku}`"
        class="w-36 sm:w-40 shrink-0 snap-start group"
      >
        <div class="aspect-square bg-surface rounded-card overflow-hidden mb-2 border border-border">
          <img
            v-if="thumbOf(p.photo_key)"
            :src="thumbOf(p.photo_key)!"
            :alt="p.name"
            class="w-full h-full object-contain"
            loading="lazy"
          >
          <div v-else class="w-full h-full flex items-center justify-center">
            <Icon name="heroicons:photo" class="w-8 h-8 text-ink-faint" />
          </div>
        </div>
        <p class="text-xs font-medium line-clamp-2 leading-snug mb-1 group-hover:text-primary">{{ p.name }}</p>
        <div class="flex items-baseline gap-1.5 flex-wrap">
          <span class="text-sm font-bold">{{ formatMoney(p.client_price, p.currency) }}</span>
          <span v-if="p.has_discount" class="badge-primary text-[10px]">Скидка</span>
        </div>
      </NuxtLink>
    </div>
  </div>
</template>
