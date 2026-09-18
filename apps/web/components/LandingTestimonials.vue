<template>
  <section class="container-app py-16 lg:py-20">
    <p class="text-xs font-semibold uppercase tracking-[0.2em] text-ink-faint mb-2">Отзывы</p>
    <h2 class="text-3xl font-bold mb-8">Что говорят наши клиенты</h2>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
      <div v-for="t in testimonials" :key="t.name" class="card card-hover p-6 flex flex-col">
        <div class="flex items-center gap-1 mb-4">
          <Icon v-for="i in 5" :key="i" name="heroicons:star" class="w-4 h-4 text-accent" />
        </div>
        <blockquote class="text-sm text-ink-muted leading-relaxed mb-5 flex-1">
          «{{ t.quote }}»
        </blockquote>
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-pill bg-accent-soft flex items-center justify-center text-accent font-bold text-sm shrink-0">
            {{ t.initials }}
          </div>
          <div>
            <div class="text-sm font-semibold">{{ t.name }}</div>
            <div class="text-xs text-ink-muted">{{ t.role }}</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
const testimonials = [
  {
    quote: 'Раньше согласование цены занимало два дня. Теперь захожу в кабинет — вижу свои цены, собираю корзину и оформляю заявку за 15 минут.',
    name: 'Алексей Петров',
    role: 'Снабженец, ООО «ЭлектроМонтаж»',
    initials: 'АП',
  },
  {
    quote: 'Удобно, что все заявки и история заказов в одном месте. Не нужно искать в почте — что заказывал месяц назад, какой статус.',
    name: 'Марина Козлова',
    role: 'Закупщик, ИП Козлова',
    initials: 'МК',
  },
  {
    quote: 'Менеджер оперативно создаёт аккаунт и настраивает цены. Перешли на портал — и больше не возвращаемся к заказам по телефону.',
    name: 'Дмитрий Волков',
    role: 'Директор, ТК «ВолтТрейд»',
    initials: 'ДВ',
  },
]
</script>
