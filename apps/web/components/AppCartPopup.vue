<script setup lang="ts">
// Client cart confirmation. The v2 cart intentionally exposes no media keys;
// the popup resolves the last-added productId against the current scoped lines.
const auth = useAuth()
const cartV2 = auth.isClient ? useCartV2() : null
const store = cartV2?.store

const addedLine = computed(() => {
  if (!store) return null
  const productId = store.lastAddedProductId
  if (!productId) return null

  const cart = store.cart
  const owner = store.owner
  if (!cart || !owner) return null
  const scopeMatches = owner.commercialScope === 'USER'
    ? cart.organizationId === null
    : cart.organizationId === owner.organizationId
  if (!scopeMatches) return null

  return cart.items.find((item) => item.productId === productId) ?? null
})

const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

watch(
  () => store?.lastAddedProductId,
  () => {
    if (!addedLine.value) return
    visible.value = false
    requestAnimationFrame(() => {
      visible.value = true
      clearTimeout(timer)
      timer = setTimeout(() => { visible.value = false }, 5000)
    })
  },
)

watch(
  () => store?.cart?.version,
  () => {
    if (visible.value && !addedLine.value) visible.value = false
  },
)

onBeforeUnmount(() => clearTimeout(timer))

function close() {
  visible.value = false
}
</script>

<template>
  <Teleport to="body">
    <Transition name="cart-popup">
      <section
        v-if="visible && addedLine"
        class="fixed bottom-20 right-4 z-50 w-[320px] max-w-[calc(100vw-2rem)] border border-border-strong bg-surface p-3 shadow-overlay lg:bottom-4"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <div class="flex items-start gap-3">
          <span
            class="flex size-14 shrink-0 items-center justify-center border border-border bg-surface-2 text-ink-muted"
            aria-hidden="true"
          >
            <Icon name="heroicons:shopping-bag" class="size-7" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="mb-0.5 flex items-center gap-1 text-xs font-semibold text-success-text">
              <Icon name="heroicons:check-circle" class="size-3.5 shrink-0" aria-hidden="true" />
              Добавлено в корзину
            </p>
            <p class="text-sm font-semibold leading-5 text-ink">{{ addedLine.name }}</p>
            <p class="numeric mt-0.5 text-xs text-ink-muted">
              {{ addedLine.sku }} · {{ addedLine.quantity }} шт ·
              {{ formatMoney(addedLine.lineTotal.amount, addedLine.lineTotal.currency) }}
            </p>
          </div>
          <UiIconButton label="Закрыть уведомление" size="compact" variant="ghost" @click="close">
            <Icon name="heroicons:x-mark" class="size-4" aria-hidden="true" />
          </UiIconButton>
        </div>
        <div class="mt-3 flex gap-2">
          <UiButton class="flex-1" @click="close(); navigateTo('/cart')">
            В корзину{{ store?.cart?.totalItems ? ` (${store.cart.totalItems})` : '' }}
          </UiButton>
          <UiButton variant="secondary" @click="close">Продолжить</UiButton>
        </div>
      </section>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cart-popup-enter-active,
.cart-popup-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.cart-popup-enter-from,
.cart-popup-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
@media (prefers-reduced-motion: reduce) {
  .cart-popup-enter-active,
  .cart-popup-leave-active {
    transition: none;
  }
}
</style>
