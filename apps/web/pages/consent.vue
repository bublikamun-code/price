<script setup lang="ts">
definePageMeta({ layout: 'auth', middleware: ['auth', 'role'], roles: ['CLIENT'] })
useHead({ title: 'Согласие на обработку ПДн' })

const auth = useAuth()
const route = useRoute()
const accepted = ref(false)
const loading = ref(false)
const errorMsg = ref('')

async function onSubmit() {
  if (loading.value || !accepted.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    await auth.updateMe({ consent_accepted: true })
    await navigateTo(getSafeRedirectPath(route.query.redirect, '/dashboard'))
  } catch (e) {
    errorMsg.value = getErrorMessage(e, 'Не удалось сохранить согласие')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <UiPanel class="p-6 sm:p-8">
    <PageHeading
      eyebrow="Доступ к кабинету"
      title="Согласие на обработку персональных данных"
      description="Для работы портала нам нужно ваше согласие. Краткая выжимка политики:"
    />

    <ul class="mb-6 flex flex-col gap-3 border-y border-border py-5 text-sm text-ink">
      <li class="flex gap-3">
        <Icon name="heroicons:shield-check" class="size-5 shrink-0 text-action" aria-hidden="true" />
        <span>Мы обрабатываем ваши ФИО, контакты и данные компании исключительно для оформления заявок и отображения персональных цен.</span>
      </li>
      <li class="flex gap-3">
        <Icon name="heroicons:lock-closed" class="size-5 shrink-0 text-action" aria-hidden="true" />
        <span>Обработка осуществляется в соответствии с Законом РБ «О защите персональных данных» — сбор, хранение, использование, обезличивание.</span>
      </li>
      <li class="flex gap-3">
        <Icon name="heroicons:eye-slash" class="size-5 shrink-0 text-action" aria-hidden="true" />
        <span>Персональные данные не передаются третьим лицам, кроме случаев, предусмотренных законодательством РБ.</span>
      </li>
      <li class="flex gap-3">
        <Icon name="heroicons:arrow-path" class="size-5 shrink-0 text-action" aria-hidden="true" />
        <span>Согласие можно отозвать — обратитесь к вашему менеджеру; данные удаляются/уничтожаются в установленный срок.</span>
      </li>
    </ul>

    <form class="flex flex-col gap-4" @submit.prevent="onSubmit">
      <UiCheckbox
        v-model="accepted"
        label="Принимаю условия обработки персональных данных"
        :disabled="loading"
      />

      <UiErrorState
        v-if="errorMsg"
        title="Не удалось сохранить согласие"
        :description="errorMsg"
      />

      <UiButton
        type="submit"
        size="touch"
        class="w-full"
        :loading="loading"
        :disabled="!accepted"
      >
        {{ loading ? 'Сохранение…' : 'Продолжить' }}
      </UiButton>
    </form>
  </UiPanel>
</template>
