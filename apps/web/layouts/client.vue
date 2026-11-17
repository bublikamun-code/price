<script setup lang="ts">
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

const route = useRoute()
const auth = useAuth()
const cart = useCartV2()
const reviewOpen = ref(false)
// Корзина и «Текущая заявка» — только для роли CLIENT (SITEMAP §3).
const isClient = computed(() => auth.isClient)
const showRequestEntry = computed(() => isClient.value && !['/cart', '/checkout'].includes(route.path))

// Корзину грузим только для клиента: у MANAGER/ADMIN запрос /api/v2/cart
// не должен уходить (бэк отвечает 403 «Корзина доступна только клиентам»).
// Создание самого useCartV2() сети не трогает — запрос идёт из ensureLoaded().
let stopCartWatch: (() => void) | null = null
onMounted(() => {
  stopCartWatch = watch(
    () => auth.isClient,
    (client) => {
      if (!client) return
      void cart.ensureLoaded().catch(() => undefined)
    },
    { immediate: true },
  )
})
onBeforeUnmount(() => {
  stopCartWatch?.()
})
</script>

<template>
  <div class="min-h-screen bg-background text-ink">
    <MobileClientHeader />
    <ClientHeader />
    <div class="flex min-h-[calc(100dvh-3.5rem)] justify-center lg:min-h-[calc(100dvh-4rem)]">
      <div class="container-app flex w-full items-start px-3 sm:px-4 lg:gap-8 lg:px-6">
        <ClientSidebar />
        <AppOfflineBanner />
        <main class="min-w-0 flex-1 py-4 pb-28 sm:py-6 lg:py-8 lg:pb-10">
          <div v-if="showRequestEntry" class="mb-5 lg:mb-6">
            <CurrentRequestStrip @open="reviewOpen = true" />
          </div>
          <slot />
        </main>
      </div>
    </div>
    <RequestReviewSheet v-if="isClient" v-model:open="reviewOpen" />
    <MobileClientNav />
  </div>
</template>
