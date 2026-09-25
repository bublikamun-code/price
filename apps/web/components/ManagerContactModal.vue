<script setup lang="ts">
const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const { request } = useApi()
const form = reactive({ company: '', name: '', phone: '', message: '' })
const sent = ref(false)
const submitting = ref(false)
const errorMessage = ref('')

const open = computed({
  get: () => props.show,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})

const canSubmit = computed(() =>
  form.company.trim().length >= 2
  && form.name.trim().length >= 2
  && form.phone.trim().length >= 7
  && !submitting.value,
)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    await request('/api/v1/public/lead', {
      method: 'POST',
      body: {
        company: form.company.trim(),
        contact_name: form.name.trim(),
        phone: form.phone.trim(),
        comment: form.message.trim() || undefined,
      },
    })
    sent.value = true
  } catch (cause) {
    errorMessage.value = getErrorMessage(cause, 'Не удалось отправить заявку')
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.show,
  (isOpen) => {
    if (!isOpen) return
    sent.value = false
    errorMessage.value = ''
  },
)
</script>

<template>
  <UiDialog
    v-model:open="open"
    title="Запросить прайс и доступ"
    description="Оставьте контакты — менеджер свяжется с вами и подготовит персональные цены по вашему договору."
  >
    <div v-if="sent" class="border-y border-success/40 bg-success-soft px-4 py-6" role="status">
      <h3 class="font-bold text-ink">Заявка отправлена</h3>
      <p class="mt-2 text-sm leading-6 text-ink-muted">
        Менеджер свяжется с вами по указанному телефону и подготовит коммерческие условия.
      </p>
    </div>

    <form v-else class="flex flex-col gap-4" @submit.prevent="submit">
      <UiField for="manager-contact-company" label="Компания" required>
        <UiInput v-model="form.company" type="text" required placeholder="ООО «Компания»" />
      </UiField>
      <UiField for="manager-contact-name" label="Контактное лицо" required>
        <UiInput v-model="form.name" type="text" required placeholder="Иван Иванов" />
      </UiField>
      <UiField for="manager-contact-phone" label="Телефон" required>
        <UiInput v-model="form.phone" type="tel" required placeholder="+375 (__) ___-__-__" />
      </UiField>
      <UiField
        for="manager-contact-message"
        label="Комментарий"
        description="Номенклатура, объём или условия поставки"
      >
        <UiTextarea
          v-model="form.message"
          :rows="3"
          placeholder="Что именно нужно подготовить"
        />
      </UiField>

      <p
        v-if="errorMessage"
        class="border border-danger/40 bg-danger-soft p-3 text-sm text-danger-text"
        role="alert"
      >
        {{ errorMessage }}
      </p>

      <UiButton
        type="submit"
        size="touch"
        class="w-full"
        :loading="submitting"
        :disabled="!canSubmit"
      >
        {{ submitting ? 'Отправляем' : 'Отправить заявку' }}
      </UiButton>
    </form>
  </UiDialog>
</template>
