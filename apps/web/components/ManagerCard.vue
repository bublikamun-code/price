<script setup lang="ts">
export interface ManagerContact {
  full_name: string
  email?: string | null
  phone?: string | null
  telegram_username?: string | null
}

const props = defineProps<{ manager?: ManagerContact | null }>()

const initials = computed(() => {
  if (!props.manager?.full_name) return '—'
  return props.manager.full_name
    .split(' ')
    .map((part) => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('')
})

const telegramLink = computed(() => {
  const username = props.manager?.telegram_username?.replace(/^@/, '')
  return username ? `https://t.me/${username}` : null
})

const whatsappLink = computed(() => {
  const phone = props.manager?.phone?.replace(/\D/g, '')
  return phone ? `https://wa.me/${phone}` : null
})
</script>

<template>
  <section v-if="manager" class="border border-border bg-surface" aria-labelledby="manager-contact-heading">
    <header class="flex items-center gap-3 border-b border-border px-4 py-3">
      <span class="grid size-10 shrink-0 place-items-center bg-service text-sm font-bold text-ink-on-service" aria-hidden="true">
        {{ initials }}
      </span>
      <div class="min-w-0">
        <p class="text-xs font-semibold text-ink-muted">Ваш менеджер</p>
        <h2 id="manager-contact-heading" class="truncate text-sm font-bold text-ink">{{ manager.full_name }}</h2>
      </div>
    </header>

    <div class="divide-y divide-border">
      <a v-if="manager.phone" :href="`tel:${manager.phone}`" class="flex min-h-11 items-center gap-3 px-4 py-2 text-sm font-semibold text-action hover:bg-surface-2">
        <Icon name="heroicons:phone" class="size-4 shrink-0" aria-hidden="true" />
        <span class="numeric">{{ manager.phone }}</span>
      </a>
      <a v-if="manager.email" :href="`mailto:${manager.email}`" class="flex min-h-11 items-center gap-3 px-4 py-2 text-sm font-semibold text-action hover:bg-surface-2">
        <Icon name="heroicons:envelope" class="size-4 shrink-0" aria-hidden="true" />
        <span class="truncate">{{ manager.email }}</span>
      </a>
      <a v-if="telegramLink" :href="telegramLink" target="_blank" rel="noopener noreferrer" class="flex min-h-11 items-center gap-3 px-4 py-2 text-sm font-semibold text-action hover:bg-surface-2">
        <Icon name="simple-icons:telegram" class="size-4 shrink-0" aria-hidden="true" />
        <span>@{{ manager.telegram_username }}</span>
      </a>
      <a v-if="whatsappLink" :href="whatsappLink" target="_blank" rel="noopener noreferrer" class="flex min-h-11 items-center gap-3 px-4 py-2 text-sm font-semibold text-action hover:bg-surface-2">
        <Icon name="simple-icons:whatsapp" class="size-4 shrink-0" aria-hidden="true" />
        <span>WhatsApp</span>
      </a>
    </div>
  </section>
</template>
