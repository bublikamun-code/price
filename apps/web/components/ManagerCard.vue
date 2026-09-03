<script setup lang="ts">
// Карточка персонального менеджера клиента (сайдбар layouts/client).
// Ссылки на звонок/mailto/Telegram/WhatsApp собираются из полей менеджера.
export interface ManagerContact {
  full_name: string
  email?: string | null
  phone?: string | null
  telegram_username?: string | null
}

const props = defineProps<{ manager?: ManagerContact | null }>()

const initials = computed(() => {
  if (!props.manager?.full_name) return '?'
  return props.manager.full_name
    .split(' ')
    .map((p) => p.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('')
})

const telegramLink = computed(() => {
  if (!props.manager?.telegram_username) return null
  const username = props.manager.telegram_username.replace(/^@/, '')
  return `https://t.me/${username}`
})

const whatsappLink = computed(() => {
  if (!props.manager?.phone) return null
  const phone = props.manager.phone.replace(/\D/g, '')
  return `https://wa.me/${phone}`
})
</script>

<template>
  <div v-if="manager" class="card p-4">
    <p class="text-xs font-medium text-ink-muted uppercase tracking-wide mb-3">Ваш менеджер</p>
    <div class="flex items-center gap-3 mb-4">
      <span class="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold">
        {{ initials }}
      </span>
      <div class="min-w-0">
        <p class="font-semibold text-ink truncate">{{ manager.full_name }}</p>
        <p v-if="manager.email" class="text-xs text-ink-muted truncate">{{ manager.email }}</p>
      </div>
    </div>
    <div class="space-y-2">
      <a v-if="manager.phone" :href="`tel:${manager.phone}`" class="flex items-center gap-2 text-sm text-primary hover:underline">
        <Icon name="heroicons:phone" class="w-4 h-4" />
        <span>{{ manager.phone }}</span>
      </a>
      <a v-if="manager.email" :href="`mailto:${manager.email}`" class="flex items-center gap-2 text-sm text-primary hover:underline">
        <Icon name="heroicons:envelope" class="w-4 h-4" />
        <span>{{ manager.email }}</span>
      </a>
      <a v-if="telegramLink" :href="telegramLink" target="_blank" rel="noopener noreferrer" class="flex items-center gap-2 text-sm text-primary hover:underline">
        <Icon name="simple-icons:telegram" class="w-4 h-4" />
        <span>@{{ manager.telegram_username }}</span>
      </a>
      <a v-if="whatsappLink" :href="whatsappLink" target="_blank" rel="noopener noreferrer" class="flex items-center gap-2 text-sm text-primary hover:underline">
        <Icon name="simple-icons:whatsapp" class="w-4 h-4" />
        <span>WhatsApp</span>
      </a>
    </div>
  </div>
</template>
