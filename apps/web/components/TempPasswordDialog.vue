<script setup lang="ts">
// Диалог показа временного пароля (создание клиента / сброс пароля, этап 8).
// Пароль выдаётся один раз — бэкенд его не хранит в открытом виде.
const props = defineProps<{ password: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function copy() {
  try {
    await navigator.clipboard.writeText(props.password)
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => (copied.value = false), 2000)
  } catch {
    // clipboard недоступен (нет HTTPS/права) — пароль остаётся видимым для ручного копирования
  }
}

onUnmounted(() => {
  if (copiedTimer) clearTimeout(copiedTimer)
})
</script>

<template>
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
    @click.self="emit('close')"
  >
    <div class="card max-w-md w-full p-6">
      <div class="flex items-start justify-between gap-4 mb-4">
        <h3 class="font-semibold">Временный пароль</h3>
        <button class="btn-ghost p-2 -mr-2 shrink-0" @click="emit('close')">
          <Icon name="heroicons:x-mark" class="w-5 h-5" />
        </button>
      </div>

      <div class="badge-warning mb-4">
        <Icon name="heroicons:exclamation-triangle" class="w-4 h-4" />
        Пароль показывается только один раз
      </div>
      <p class="text-sm text-ink-muted mb-4">
        Передайте пароль клиенту для входа в портал. После входа его можно будет сменить.
      </p>

      <div class="flex items-center gap-3 mb-5">
        <code class="flex-1 px-4 py-3 rounded-card bg-canvas border border-border font-mono text-base break-all select-all">{{ password }}</code>
        <button class="btn-secondary shrink-0" @click="copy">
          <Icon :name="copied ? 'heroicons:check' : 'heroicons:clipboard-document'" class="w-4 h-4" />
          {{ copied ? 'Скопировано' : 'Копировать' }}
        </button>
      </div>

      <button class="btn-primary w-full" @click="emit('close')">Готово</button>
    </div>
  </div>
</template>
