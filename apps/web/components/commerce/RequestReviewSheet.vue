<script setup lang="ts">
import type { CartLine } from '~/domain/api/v2/cart.schema'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const cart = useCartV2()
const cartLines = computed(() => cart.store.cart?.items ?? [])
const total = computed(() => cart.store.cart?.total)
const busy = ref<string | null>(null)
const error = ref('')

watch(() => props.open, (open) => {
  if (open) void cart.ensureLoaded().catch(() => undefined)
})

async function changeQuantity(line: CartLine, delta: number) {
  const quantity = line.quantity + delta
  if (quantity < 1 || busy.value) return
  busy.value = line.productId
  error.value = ''
  try {
    await cart.replaceItem(line.productId, { quantity: String(quantity), note: line.note })
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось изменить количество')
  } finally {
    busy.value = null
  }
}
async function removeLine(line: CartLine) {
  if (busy.value) return
  busy.value = line.productId
  error.value = ''
  try {
    await cart.removeItem(line.productId)
  } catch (cause) {
    error.value = getErrorMessage(cause, 'Не удалось удалить позицию')
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <UiSheet :open="open" title="Текущая заявка" description="Проверьте позиции перед оформлением." side="bottom" @update:open="emit('update:open', $event)">
    <div v-if="!cartLines.length" class="py-10 text-center">
      <Icon name="heroicons:clipboard-document-list" class="mx-auto size-10 text-ink-faint" aria-hidden="true" />
      <p class="mt-4 text-base font-semibold text-ink">Заявка пока пуста</p>
      <p class="mt-1 text-sm text-ink-muted">Добавьте товары из каталога.</p>
    </div>
    <div v-else>
      <p v-if="error" class="mb-3 border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger-text" role="alert">{{ error }}</p>
      <ul class="divide-y divide-border border-y border-border">
        <li v-for="line in cartLines" :key="line.productId" class="flex gap-3 py-3">
          <div class="min-w-0 flex-1">
            <NuxtLink :to="`/catalog/${line.sku}`" class="line-clamp-2 text-sm font-semibold text-ink hover:text-action">{{ line.name }}</NuxtLink>
            <p class="numeric mt-1 text-xs text-ink-muted">{{ line.sku }} · {{ line.quantity }} шт.</p>
            <strong class="numeric mt-2 block text-sm text-ink">{{ formatMoney(line.lineTotal.amount, line.lineTotal.currency) }}</strong>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-2">
            <div class="flex items-center border border-border" role="group" :aria-label="`Количество: ${line.name}`">
              <button type="button" class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="line.quantity <= 1 || busy === line.productId" :aria-label="`Уменьшить количество: ${line.name}`" @click="changeQuantity(line, -1)"><Icon name="heroicons:minus" class="size-4" aria-hidden="true" /></button>
              <span class="numeric w-8 text-center text-sm font-semibold">{{ line.quantity }}</span>
              <button type="button" class="flex size-11 items-center justify-center text-ink-muted hover:bg-surface-2 disabled:opacity-40" :disabled="busy === line.productId" :aria-label="`Увеличить количество: ${line.name}`" @click="changeQuantity(line, 1)"><Icon name="heroicons:plus" class="size-4" aria-hidden="true" /></button>
            </div>
            <button type="button" class="inline-flex min-h-11 items-center px-2 text-xs font-semibold text-danger-text hover:underline disabled:opacity-50" :disabled="busy === line.productId" @click="removeLine(line)">Удалить</button>
          </div>
        </li>
      </ul>
      <div class="mt-4 flex items-baseline justify-between">
        <span class="text-sm text-ink-muted">Итого</span>
        <strong v-if="total" class="numeric text-xl font-bold text-ink">{{ formatMoney(total.amount, total.currency) }}</strong>
      </div>
    </div>
    <template #footer>
      <NuxtLink v-if="cartLines.length" to="/checkout" class="flex min-h-11 w-full items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on">Перейти к оформлению <Icon name="heroicons:arrow-right" class="ml-2 size-4" aria-hidden="true" /></NuxtLink>
      <NuxtLink v-else to="/catalog" class="flex min-h-11 w-full items-center justify-center border border-action bg-action px-4 text-sm font-semibold text-action-on">Открыть каталог</NuxtLink>
    </template>
  </UiSheet>
</template>
