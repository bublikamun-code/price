<script setup lang="ts">
import { COMPANY_COPYRIGHT_YEAR, COMPANY_NAME, SITE_URL } from '~/utils/site'
</script>

<template>
  <footer class="border-t border-white/10 bg-service text-ink-on-service">
    <div class="container-app py-10">
      <div class="grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-10">
        <div>
          <NuxtLink to="/" class="inline-flex min-h-11 items-center" aria-label="Price Portal — главная">
            <span class="numeric text-lg font-bold text-ink-on-service">PRICE<span class="text-action">/</span>WEB</span>
          </NuxtLink>
          <p class="mt-3 text-sm leading-6 text-ink-on-service/70">
            {{ COMPANY_NAME }}<br>
            <a :href="SITE_URL" class="hover:text-action">{{ SITE_URL }}</a>
          </p>
        </div>
        <div>
          <h2 class="text-xs font-bold uppercase text-ink-on-service">Связаться</h2>
          <nav class="mt-3 grid text-sm" aria-label="Связаться">
            <NuxtLink to="/#lead" class="inline-flex min-h-11 items-center text-ink-on-service/70 hover:text-action">Запросить прайс и доступ</NuxtLink>
            <NuxtLink to="/login" class="inline-flex min-h-11 items-center text-ink-on-service/70 hover:text-action">Вход для клиентов</NuxtLink>
          </nav>
        </div>
        <div>
          <h2 class="text-xs font-bold uppercase text-ink-on-service">Разделы</h2>
          <nav class="mt-3 grid text-sm" aria-label="Разделы сайта">
            <NuxtLink to="/brands" class="inline-flex min-h-11 items-center text-ink-on-service/70 hover:text-action">Каталог брендов</NuxtLink>
            <NuxtLink to="/news" class="inline-flex min-h-11 items-center text-ink-on-service/70 hover:text-action">Новости</NuxtLink>
          </nav>
        </div>
        <div>
          <h2 class="text-xs font-bold uppercase text-ink-on-service">Правовая информация</h2>
          <nav class="mt-3 grid text-sm" aria-label="Правовая информация">
            <NuxtLink to="/privacy" class="inline-flex min-h-11 items-center text-ink-on-service/70 hover:text-action">Политика конфиденциальности</NuxtLink>
          </nav>
          <p class="mt-3 text-xs leading-5 text-ink-on-service/60">Юридические реквизиты стороны указываются в договоре и документах заказа.</p>
        </div>
      </div>
      <div class="mt-8 flex flex-col gap-2 border-t border-white/10 pt-5 text-xs text-ink-on-service/70 sm:flex-row sm:items-center sm:justify-between">
        <p>© {{ COMPANY_COPYRIGHT_YEAR }} {{ COMPANY_NAME }}. Все права защищены.</p>
        <p class="font-mono uppercase">B2B COMMERCE SYSTEM</p>
      </div>
    </div>
  </footer>
</template>
