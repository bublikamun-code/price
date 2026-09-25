<script setup lang="ts">
useHead({ meta: [{ name: 'robots', content: 'noindex, nofollow' }] })
</script>

<template>
  <div class="flex min-h-dvh flex-col bg-background text-ink">
    <header class="border-b border-border bg-surface">
      <div class="container-app flex h-16 items-center justify-between gap-6">
        <NuxtLink to="/" class="font-bold tracking-tight" aria-label="PricePortal — на главную">
          <span class="text-action">Price</span><span class="text-ink">Portal</span>
        </NuxtLink>
        <NuxtLink to="/" class="text-sm font-semibold text-ink-muted underline underline-offset-4 hover:text-ink">
          На главную
        </NuxtLink>
      </div>
    </header>

    <main class="flex-1">
      <div class="grid min-h-[calc(100dvh-9rem)] w-full lg:grid-cols-[minmax(22rem,0.8fr)_minmax(28rem,1fr)]">
        <aside class="flex flex-col justify-between border-b border-border bg-service px-5 py-12 text-ink-on-service sm:px-10 lg:min-h-[42rem] lg:border-b-0 lg:border-r lg:px-12 lg:py-16" aria-label="О кабинете">
          <div>
            <p class="text-sm font-semibold text-ink-on-service/70">Рабочее место закупщика</p>
            <p class="mt-5 max-w-xl text-4xl font-extrabold leading-[1.08] tracking-[-0.035em] sm:text-5xl">
              Каталог, цены и заявки — в одном контуре
            </p>
            <p class="mt-6 max-w-lg text-base leading-7 text-ink-on-service/80">
              Вход открывает персональный прайс, текущую заявку, историю заказов и настройки рабочего кабинета.
            </p>
          </div>

          <ol class="mt-12 divide-y divide-ink-on-service/25 border-y border-ink-on-service/25">
            <li class="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 py-4">
              <span class="font-mono text-sm text-ink-on-service/60">01</span>
              <span class="text-sm font-semibold">Подтвердите вход</span>
            </li>
            <li class="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 py-4">
              <span class="font-mono text-sm text-ink-on-service/60">02</span>
              <span class="text-sm font-semibold">При необходимости введите код 2FA</span>
            </li>
            <li class="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 py-4">
              <span class="font-mono text-sm text-ink-on-service/60">03</span>
              <span class="text-sm font-semibold">Продолжите по сохранённому безопасному адресу</span>
            </li>
          </ol>
        </aside>

        <section class="flex items-center px-5 py-12 sm:px-10 lg:px-12 lg:py-16 xl:px-16" aria-label="Форма авторизации">
          <div class="w-full max-w-md">
            <slot />
          </div>
        </section>
      </div>
    </main>

    <AppFooter />
  </div>
</template>
