<script setup lang="ts">
// Всплывающая корзина снизу справа при добавлении товара.
// Срабатывает на lastAdded из useCart (module-level ref — виден со всех страниц).
const { lastAdded, cart } = useCart()
const { thumbOf } = useProductPhoto()

const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

watch(lastAdded, (item) => {
  if (!item) return
  visible.value = false
  requestAnimationFrame(() => {
    visible.value = true
    clearTimeout(timer)
    timer = setTimeout(() => { visible.value = false }, 5000)
  })
})

function close() {
  visible.value = false
}
</script>

<template>
  <Teleport to="body">
    <Transition name="cart-popup">
      <div
        v-if="visible && lastAdded"
        class="fixed right-4 bottom-20 lg:bottom-4 z-50 card p-3 shadow-card w-[320px] max-w-[calc(100vw-2rem)]"
        role="status"
      >
        <div class="flex items-start gap-3">
          <img
            v-if="thumbOf(lastAdded.photo_key)"
            :src="thumbOf(lastAdded.photo_key) ?? undefined"
            :alt="lastAdded.name"
            class="w-14 h-14 rounded-lg object-contain bg-canvas shrink-0"
          >
          <span v-else class="w-14 h-14 rounded-lg bg-canvas text-ink-faint flex items-center justify-center shrink-0">
            <Icon name="heroicons:photo" class="w-7 h-7" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium text-success-text flex items-center gap-1 mb-0.5">
              <Icon name="heroicons:check-circle" class="w-3.5 h-3.5 shrink-0" />
              Добавлено в корзину
            </p>
            <p class="text-sm font-medium text-ink leading-snug line-clamp-2">{{ lastAdded.name }}</p>
            <p class="text-xs text-ink-faint mt-0.5">
              {{ lastAdded.quantity }} шт · {{ formatMoney(lastAdded.line_total, lastAdded.currency) }}
            </p>
          </div>
          <button class="btn-ghost p-1 shrink-0 -mt-1 -mr-1" title="Закрыть" @click="close">
            <Icon name="heroicons:x-mark" class="w-4 h-4" />
          </button>
        </div>
        <div class="flex gap-2 mt-3">
          <NuxtLink to="/cart" class="btn-primary flex-1 justify-center py-2 text-sm" @click="close">
            В корзину{{ cart?.total_items ? ` (${cart.total_items})` : '' }}
          </NuxtLink>
          <button class="btn-ghost px-3 py-2 text-sm" @click="close">Продолжить</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cart-popup-enter-active,
.cart-popup-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.cart-popup-enter-from,
.cart-popup-leave-to {
  opacity: 0;
  transform: translateY(12px);
}
</style>
