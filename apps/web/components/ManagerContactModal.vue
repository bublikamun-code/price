<script setup lang="ts">
// Модал «Связаться с менеджером»: контакты + форма, уходит письмом через
// mailto (бэкенд-заявок на связь в §6 нет — при появлении заменить submit).
import {
  COMPANY_PHONE,
  COMPANY_PHONE_HREF,
  COMPANY_EMAIL,
  COMPANY_EMAIL_HREF,
} from '~/utils/site'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const form = reactive({ name: '', contact: '', message: '' })
const sent = ref(false)
const nameInput = ref<HTMLInputElement | null>(null)

const mailtoHref = computed(() => {
  const subject = encodeURIComponent(`Запрос с портала — ${form.name || 'без имени'}`)
  const body = encodeURIComponent(
    `Имя: ${form.name}\nКонтакт: ${form.contact}\n\n${form.message}`.trim(),
  )
  return `${COMPANY_EMAIL_HREF}?subject=${subject}&body=${body}`
})

function submit() {
  if (!form.name.trim() || !form.contact.trim()) return
  window.location.href = mailtoHref.value
  sent.value = true
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.show,
  (open) => {
    if (open) {
      sent.value = false
      nextTick(() => nameInput.value?.focus())
      window.addEventListener('keydown', onKey)
    } else {
      window.removeEventListener('keydown', onKey)
    }
  },
)
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/60 backdrop-blur-sm"
        aria-modal="true"
        role="dialog"
        aria-label="Связаться с менеджером"
      >
        <div class="absolute inset-0" aria-hidden="true" @click="emit('close')" />
        <div class="relative w-full max-w-lg max-h-[90vh] overflow-y-auto scrollbar-none card p-6 sm:p-8 shadow-card">
          <button
            type="button"
            class="absolute top-4 right-4 btn-ghost p-1.5 rounded-full transition-colors duration-150"
            aria-label="Закрыть"
            @click="emit('close')"
          >
            <Icon name="heroicons:x-mark" class="w-5 h-5" />
          </button>

          <h2 class="text-2xl font-bold mb-1">Связаться с менеджером</h2>
          <p class="text-sm text-ink-muted mb-5">
            Оставьте контакты — менеджер свяжется с вами и подготовит персональные цены по вашему
            договору.
          </p>

          <!-- Контактные данные менеджера -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
            <a
              :href="COMPANY_PHONE_HREF"
              class="flex items-center gap-3 rounded-card border border-border p-3.5 transition-colors duration-150 hover:bg-canvas"
            >
              <Icon name="heroicons:phone" class="w-5 h-5 shrink-0 text-primary" />
              <span>
                <span class="block text-xs text-ink-faint">Телефон</span>
                <span class="block text-sm font-medium">{{ COMPANY_PHONE }}</span>
              </span>
            </a>
            <a
              :href="COMPANY_EMAIL_HREF"
              class="flex items-center gap-3 rounded-card border border-border p-3.5 transition-colors duration-150 hover:bg-canvas"
            >
              <Icon name="heroicons:envelope" class="w-5 h-5 shrink-0 text-primary" />
              <span>
                <span class="block text-xs text-ink-faint">Email</span>
                <span class="block text-sm font-medium">{{ COMPANY_EMAIL }}</span>
              </span>
            </a>
          </div>

          <form class="flex flex-col gap-4" @submit.prevent="submit">
            <label class="flex flex-col gap-1.5 text-sm">
              <span class="text-ink-muted">Ваше имя</span>
              <input
                ref="nameInput"
                v-model="form.name"
                type="text"
                required
                autocomplete="name"
                placeholder="Иван Иванов"
                class="input w-full"
              >
            </label>
            <label class="flex flex-col gap-1.5 text-sm">
              <span class="text-ink-muted">Телефон или email</span>
              <input
                v-model="form.contact"
                type="text"
                required
                placeholder="+375 (__) ___-__-__ или you@company.by"
                class="input w-full"
              >
            </label>
            <label class="flex flex-col gap-1.5 text-sm">
              <span class="text-ink-muted">Сообщение</span>
              <textarea
                v-model="form.message"
                rows="3"
                placeholder="Интересуют цены по договору — обсуждение условий"
                class="input w-full resize-none"
              />
            </label>

            <div v-if="sent" class="flex items-start gap-2 rounded-card border border-border p-3 text-sm text-ink-muted">
              <Icon name="heroicons:check-circle" class="w-5 h-5 shrink-0 text-primary" />
              <span>
                Почтовый клиент открыт — письмо осталось только отправить. Если оно не открылось,
                напишите напрямую на
                <a :href="COMPANY_EMAIL_HREF" class="text-primary hover:underline">{{ COMPANY_EMAIL }}</a>
                или позвоните: {{ COMPANY_PHONE }}.
              </span>
            </div>

            <button type="submit" class="btn-primary w-full py-3" :disabled="!form.name.trim() || !form.contact.trim()">
              <Icon name="heroicons:paper-airplane" class="w-5 h-5" />
              Отправить письмо
            </button>
            <p class="text-xs text-ink-faint text-center">
              Нажимая кнопку, вы открываете черновик письма менеджеру со своими контактами.
            </p>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
