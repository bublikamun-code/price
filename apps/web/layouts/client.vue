<script setup lang="ts">
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })

const route = useRoute()
const cart = useCartV2()
const reviewOpen = ref(false)
const showRequestEntry = computed(() => !['/cart', '/checkout'].includes(route.path))

onMounted(() => {
  void cart.ensureLoaded().catch(() => undefined)
})
</script>

<template>
  <div class="min-h-screen bg-background text-ink">
    <MobileClientHeader />
    <ClientHeader />
    <div class="flex min-h-[calc(100dvh-3.5rem)] justify-center lg:min-h-[calc(100dvh-4rem)]">
      <div class="container-app flex w-full items-start px-3 sm:px-4 lg:px-6">
        <ClientSidebar />
        <main class="min-w-0 flex-1 py-4 pb-28 sm:py-6 lg:py-8 lg:pb-10">
          <div v-if="showRequestEntry" class="mb-5 lg:mb-6">
            <CurrentRequestStrip @open="reviewOpen = true" />
          </div>
          <slot />
        </main>
      </div>
    </div>
    <RequestReviewSheet v-model:open="reviewOpen" />
    <MobileClientNav />
  </div>
</template>
