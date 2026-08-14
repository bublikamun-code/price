<script setup lang="ts">
// Главная страница (публичная). См. SITEMAP.md §5.
useHead({ title: 'Главная' })

const advantages = [
  { icon: 'heroicons:currency-dollar', title: 'Персональные цены', text: 'Индивидуальные скидки по брендам и актуальные прайсы напрямую от менеджера.' },
  { icon: 'heroicons:bolt', title: 'Актуальный прайс', text: 'Каталог обновляется по CSV. Цены и статусы всегда свежие.' },
  { icon: 'heroicons:clipboard-document-check', title: 'Быстрые заявки', text: 'Корзина, массовое добавление по артикулам, повтор заказа в один клик.' },
  { icon: 'heroicons:document-text', title: 'Каталоги брендов', text: 'PDF-каталоги и спец-выгрузки для вашего интернет-магазина.' },
]
</script>

<template>
  <div>
    <!-- Hero -->
    <section class="relative overflow-hidden">
      <div class="container-app py-16 lg:py-24 text-center">
        <span class="chip bg-primary-soft text-primary mb-6">B2B-портал</span>
        <h1 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-5 leading-tight">
          Персональный доступ к прайсам<br class="hidden sm:block" >
          и управлению заявками
        </h1>
        <p class="text-lg text-ink-muted max-w-2xl mx-auto mb-8">
          Личный кабинет с динамическими ценами по вашему договору, импорт заявок и уведомления в реальном времени.
        </p>
        <div class="flex items-center justify-center gap-3">
          <NuxtLink to="/login" class="btn-primary px-6 py-3 text-base">Войти в личный кабинет</NuxtLink>
          <a href="#" class="btn-outline px-6 py-3 text-base">Связаться с менеджером</a>
        </div>
      </div>
    </section>

    <!-- Преимущества -->
    <section class="container-app py-12 lg:py-16">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <div v-for="a in advantages" :key="a.title" class="card card-hover p-6">
          <div class="w-12 h-12 rounded-card bg-primary-soft text-primary flex items-center justify-center mb-4">
            <Icon :name="a.icon" class="w-6 h-6" />
          </div>
          <h3 class="text-lg font-semibold mb-2">{{ a.title }}</h3>
          <p class="text-sm text-ink-muted leading-relaxed">{{ a.text }}</p>
        </div>
      </div>
    </section>

    <!-- Как начать -->
    <section class="bg-surface border-y border-border">
      <div class="container-app py-12 lg:py-16">
        <h2 class="text-2xl font-bold text-center mb-10">Как начать работу</h2>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div
v-for="(step, i) in [
            { t: 'Менеджер создаёт аккаунт', d: 'Вы получаете логин и временный пароль от вашего персонального менеджера.' },
            { t: 'Вход и согласие', d: 'Первый вход — принимаете условия обработки персональных данных.' },
            { t: 'Заказ и отслеживание', d: 'Собираете корзину, оформляете заявку и следите за статусом в реальном времени.' },
          ]" :key="i" class="flex gap-4">
            <div class="shrink-0 w-10 h-10 rounded-pill bg-secondary-soft text-secondary flex items-center justify-center font-bold">{{ i + 1 }}</div>
            <div>
              <h4 class="font-semibold mb-1">{{ step.t }}</h4>
              <p class="text-sm text-ink-muted">{{ step.d }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
