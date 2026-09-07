<script setup lang="ts">
// Footer — см. SITEMAP.md §2. Реквизиты ООО «Свет в доме».
const COMPANY_NAME = 'ООО «Свет в доме»'
const COMPANY_ADDRESS = 'Республика Беларусь, г. Минск, ул. Примерная, д. 1, офис 1'
const COMPANY_UNP = '123456789'
const COMPANY_PHONE = '+375 (29) 123-45-67'
const COMPANY_PHONE_HREF = 'tel:+375291234567'
const COMPANY_EMAIL = 'info@svetvdome.by'
const COMPANY_EMAIL_HREF = 'mailto:info@svetvdome.by'
const COMPANY_COPYRIGHT_YEAR = 2026
</script>

<template>
  <footer class="bg-[#0a0a0a] text-white/80 border-t border-white/10 mt-12 lg:mt-16">
    <div class="container-app py-10 lg:py-12">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 lg:gap-12">
        <!-- Логотип и адрес -->
        <div class="space-y-4">
          <NuxtLink to="/" class="inline-block">
            <span class="text-xl font-bold">
              <span class="text-white">Price</span><span class="text-white">Portal</span>
            </span>
          </NuxtLink>
          <p class="text-sm text-white/70 leading-relaxed">
            {{ COMPANY_NAME }}<br>
            {{ COMPANY_ADDRESS }}
          </p>
        </div>

        <!-- Контакты -->
        <div class="space-y-4">
          <h3 class="text-sm font-semibold uppercase tracking-wide text-white/90">
            Контакты
          </h3>
          <ul class="space-y-2 text-sm">
            <li>
              <a :href="COMPANY_PHONE_HREF" class="hover:text-white transition-colors">
                {{ COMPANY_PHONE }}
              </a>
            </li>
            <li>
              <a :href="COMPANY_EMAIL_HREF" class="hover:text-white transition-colors">
                {{ COMPANY_EMAIL }}
              </a>
            </li>
          </ul>
        </div>

        <!-- Разделы -->
        <div class="space-y-4">
          <h3 class="text-sm font-semibold uppercase tracking-wide text-white/90">
            Разделы
          </h3>
          <nav class="flex flex-col gap-2 text-sm">
            <NuxtLink to="/brands" class="hover:text-white transition-colors">
              Бренды
            </NuxtLink>
            <NuxtLink to="/catalog" class="hover:text-white transition-colors">
              Каталог
            </NuxtLink>
            <NuxtLink to="/" class="hover:text-white transition-colors">
              Личный кабинет
            </NuxtLink>
            <NuxtLink to="/privacy" class="hover:text-white transition-colors">
              Политика конфиденциальности
            </NuxtLink>
          </nav>
        </div>

        <!-- Реквизиты -->
        <div class="space-y-4">
          <h3 class="text-sm font-semibold uppercase tracking-wide text-white/90">
            Реквизиты
          </h3>
          <dl class="space-y-2 text-sm text-white/70">
            <div>
              <dt class="sr-only">Название</dt>
              <dd>{{ COMPANY_NAME }}</dd>
            </div>
            <div>
              <dt class="sr-only">УНП</dt>
              <dd>УНП {{ COMPANY_UNP }}</dd>
            </div>
            <div>
              <dt class="sr-only">Юридический адрес</dt>
              <dd>{{ COMPANY_ADDRESS }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <!-- Копирайт -->
      <div class="mt-10 pt-6 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-white/50">
        <p>© {{ COMPANY_COPYRIGHT_YEAR }} {{ COMPANY_NAME }}. Все права защищены.</p>
        <p>Работает на PricePortal</p>
      </div>
    </div>
  </footer>
</template>
