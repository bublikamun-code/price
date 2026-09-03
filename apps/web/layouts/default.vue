<script setup lang="ts">
// Layout для публичных страниц (без sidebar).
// Авторизованные видят упрощённую шапку (AppHeader), гости — только «Войти».
</script>

<template>
  <div class="min-h-screen flex flex-col bg-canvas">
    <AppHeader />
    <main class="flex-1">
      <slot />
    </main>
    <footer class="border-t border-border bg-surface">
      <div class="container-app py-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 text-sm">
        <div>
          <div class="text-lg font-bold mb-2">
            <span class="text-primary">Price</span><span class="text-ink">Portal</span>
          </div>
          <p class="text-ink-muted leading-relaxed">Клиентский портал с персональными ценами и удобным каталогом.</p>
        </div>
        <div>
          <h4 class="font-semibold text-ink mb-3">Разделы</h4>
          <nav class="flex flex-col gap-2 text-ink-muted">
            <NuxtLink to="/catalog" class="hover:text-primary">Каталог</NuxtLink>
            <NuxtLink to="/orders" class="hover:text-primary">Мои заявки</NuxtLink>
            <NuxtLink to="/favorites" class="hover:text-primary">Избранное</NuxtLink>
          </nav>
        </div>
        <div>
          <h4 class="font-semibold text-ink mb-3">Контакты</h4>
          <div class="flex flex-col gap-2 text-ink-muted">
            <a href="tel:+375291234567" class="hover:text-primary">+375 (29) 123-45-67</a>
            <a href="mailto:info@svetvdome.by" class="hover:text-primary">info@svetvdome.by</a>
            <span>г. Минск, ул. Примерная, 1</span>
          </div>
        </div>
        <div>
          <h4 class="font-semibold text-ink mb-3">Реквизиты</h4>
          <div class="text-ink-muted leading-relaxed">
            <p>ООО «Свет в доме»</p>
            <p>УНП: 123456789</p>
            <p class="mt-2">
              <NuxtLink to="/privacy" class="hover:text-primary">Политика конфиденциальности</NuxtLink>
            </p>
          </div>
        </div>
      </div>
      <div class="border-t border-border">
        <div class="container-app py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-ink-faint">
          <p>© {{ new Date().getFullYear() }} ООО «Свет в доме». Все права защищены.</p>
          <p>Работает на <span class="font-medium">PricePortal</span></p>
        </div>
      </div>
    </footer>
  </div>
</template>
