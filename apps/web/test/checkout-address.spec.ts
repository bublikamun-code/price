import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const readPage = (path: string) => readFileSync(resolve(webRoot, path), 'utf8')

// Статический контракт страницы оформления (в стиле orders-filters.spec.ts):
// адресная книга доставки встроена в сабмит заявки (Этап 2).
const checkoutPage = readPage('pages/checkout.vue')

describe('client checkout delivery address book', () => {
  it('loads saved delivery addresses when the DELIVERY method is selected', () => {
    expect(checkoutPage).toContain('const addressesV2 = useOrganizationAddresses()')
    expect(checkoutPage).toMatch(
      /watch\(deliveryMethod, \(method\) => \{\s*if \(method === 'DELIVERY'\) void loadAddresses\(\)/,
    )
    expect(checkoutPage).toMatch(
      /onMounted\(\(\) => \{\s*void loadCart\(\)\s*if \(deliveryMethod\.value === 'DELIVERY'\) void loadAddresses\(\)/,
    )
  })

  it('preselects the default saved address and marks it with a badge', () => {
    expect(checkoutPage).toMatch(/find\(\(address\) => address\.isDefault\)/)
    expect(checkoutPage).toContain('data-testid="checkout-address-default-badge"')
    expect(checkoutPage).toContain('data-testid="checkout-address-option"')
    expect(checkoutPage).toContain('data-testid="checkout-address-option-new"')
  })

  it('puts the selected or freshly saved addressId into the order payload', () => {
    expect(checkoutPage).toContain('function buildPayload(addressId: string | null)')
    expect(checkoutPage).toMatch(/method: 'DELIVERY',\s*addressId,/)
    expect(checkoutPage).toContain('addressChoice.value = preferred.id')
  })

  it('saves a new address through the v2 endpoint before submitting the order', () => {
    expect(checkoutPage).toContain('function newAddressPayload(): OrganizationAddressCreate')
    expect(checkoutPage).toContain("kind: 'DELIVERY',")
    expect(checkoutPage).toContain('await addressesV2.createAddress(newAddressPayload())')
    expect(checkoutPage).toContain('data-testid="checkout-save-address"')
  })

  it('blocks the order submit when the address save is rejected as a duplicate', () => {
    expect(checkoutPage).toContain("appProblem.code === 'ADDRESS_DUPLICATE'")
    // Заказ не отправляется: ранний return до ordersV2.submit.
    expect(checkoutPage).toMatch(/addressSaveError\.value = appProblem\s*return/)
    expect(checkoutPage).toContain('data-testid="checkout-address-save-error"')
    expect(checkoutPage).toContain('Такой адрес уже сохранён в адресной книге')
  })

  it('keeps the current checkout behaviour when no saved addresses exist', () => {
    // Форма нового адреса свернута, заказ уходит без addressId (как раньше).
    expect(checkoutPage).toContain('data-testid="checkout-address-new-toggle"')
    expect(checkoutPage).toMatch(
      /savedAddresses\.value\.length\s*\?\s*addressChoice\.value === NEW_ADDRESS_CHOICE\s*:\s*showNewAddress\.value/,
    )
    expect(checkoutPage).toContain('addressesState.value = ' + "'unavailable'")
    expect(checkoutPage).toContain('data-testid="checkout-addresses-unavailable"')
  })

  it('prefills the new address form from the delivery contacts', () => {
    expect(checkoutPage).toContain('newAddressRecipient.value = deliveryContact.value')
    expect(checkoutPage).toContain('newAddressPhone.value = deliveryPhone.value')
    expect(checkoutPage).toContain('data-testid="checkout-new-address-line"')
  })
})
