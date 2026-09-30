import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FetchOptions } from 'ofetch'
import { describe, expect, it } from 'vitest'

import { createApiV2Client, type ApiRequester } from '../domain/api/v2/client'
import {
  invoiceResponseSchema,
  invoiceSchema,
  invoiceStatusPatchSchema,
  organizationRequisitesPatchSchema,
} from '../domain/api/v2/invoice.schema'
import {
  orderDetailSchema,
  orderSummarySchema,
} from '../domain/api/v2/order.schema'
import { organizationDetailResponseSchema } from '../domain/api/v2/organizations.schema'
import { AppProblem, problemMessage } from '../domain/api/v2/problem'
import {
  createInvoiceRepository,
  toIfMatch,
  type InvoicePdfTransport,
} from '../domain/invoice/invoice.repository'
import {
  INVOICE_PDF_STATUS_META,
  INVOICE_STATUS_META,
  INVOICE_STATUS_OPTIONS,
  invoiceFileName,
} from '../utils/invoice'

// Контракт счёта на оплату (§6 «Счета на оплату», §16 п.40,
// docs/API_V2_CONTRACT.md §12). Стражится форма InvoiceOut, отправка
// If-Match по версии СЧЁТА (не заказа), идемпотентность выставления,
// блок `invoice` в заказе и безопасное имя файла для байтовой выдачи PDF.

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, 'test/fixtures', name), 'utf8'))
/** Общие фикстуры API v2 лежат у бэкенда — тем же путём читают их и его тесты. */
const apiFixture = (name: string) =>
  JSON.parse(readFileSync(resolve(webRoot, '../api/tests/fixtures/v2', name), 'utf8'))

const orderId = '88888888-8888-4888-8888-888888888888'
const invoiceId = '44444444-4444-4444-8444-444444444444'
const organizationId = '22222222-2222-4222-8222-222222222222'

interface RecordedRequest {
  url: string
  options: FetchOptions
}

function requestSequence(
  responses: Array<{ body?: unknown; error?: unknown }>,
) {
  const requests: RecordedRequest[] = []
  const queue = [...responses]
  const requester: ApiRequester = async <T>(url: string, options: FetchOptions = {}) => {
    requests.push({ url, options })
    const current = queue.shift()
    if (!current) throw new Error('No response configured')
    // Ошибку отдаём как есть: клиент v2 сам превращает её в AppProblem.
    if ('error' in current) throw current.error
    return current.body as T
  }
  return { requester, requests }
}

/** Problem Details в форме ofetch: статус в error.status, тело в error.data. */
function problemResponse(
  status: number,
  code: string,
  title: string,
  detail: string,
): unknown {
  return {
    status,
    data: {
      type: 'about:blank',
      title,
      status,
      detail,
      instance: '/api/v2/problem',
      code,
      requestId: `req-${status}`,
      errors: [],
    },
  }
}

/** Транспорт байтов подменяется: домен не должен знать про DOM. */
function recordingPdf(): InvoicePdfTransport & {
  fetched: string[]
  saved: Array<{ name: string; size: number }>
} {
  const fetched: string[] = []
  const saved: Array<{ name: string; size: number }> = []
  return {
    fetched,
    saved,
    async fetch(path) {
      fetched.push(path)
      return new Blob(['%PDF-1.7 invoice'], { type: 'application/pdf' })
    },
    save(blob, fileName) {
      saved.push({ name: fileName, size: blob.size })
    },
  }
}

function headersOf(options: FetchOptions): Record<string, string> {
  return (options.headers ?? {}) as Record<string, string>
}

describe('invoice schema contract', () => {
  it('parses the canonical InvoiceOut with money, parties and due date', () => {
    const parsed = invoiceResponseSchema.parse(fixture('invoice.json'))

    expect(parsed.data).toMatchObject({
      id: invoiceId,
      orderId,
      number: 'СЧ-2026-000042',
      status: 'ISSUED',
      pdfStatus: 'PENDING',
      total: { amount: '294.90', currency: 'BYN' },
      issuedAt: '2026-09-30T08:15:00Z',
      dueAt: '2026-10-07',
      version: 1,
    })
    // Реквизиты покупателя/продавца — проекция, ключи приходят всегда (§6).
    expect(parsed.data.buyer.taxId).toBe('191234567')
    expect(parsed.data.buyer.bank?.code).toBe('BYNORBY2')
    expect(parsed.data.seller.legalName).toBe('ООО «Трейд Партс»')
  })

  it('accepts an invoice with nullable party fields and no due date', () => {
    const payload = fixture('invoice.json')
    payload.data.dueAt = null
    payload.data.buyer = {
      legalName: '—',
      taxId: null,
      legalAddress: null,
      bank: null,
    }
    const parsed = invoiceSchema.safeParse(payload.data)
    expect(parsed.success).toBe(true)
  })

  it('rejects an unknown status and a float-ish money amount', () => {
    const payload = fixture('invoice.json')
    payload.data.status = 'REFUNDED'
    expect(invoiceSchema.safeParse(payload.data).success).toBe(false)

    const moneyPayload = fixture('invoice.json')
    moneyPayload.data.total.amount = '294.9'
    expect(invoiceSchema.safeParse(moneyPayload.data).success).toBe(false)
  })

  it('rejects a payload that drops the buyer party block', () => {
    const payload = fixture('invoice.json')
    delete payload.data.seller
    expect(invoiceSchema.safeParse(payload.data).success).toBe(false)
  })

  it('carries the invoice block in the order detail and the summary in the list', () => {
    const detail = fixture('invoice.json')
    const orderDetail = {
      ...apiFixture('order_detail_success.json').data,
      invoice: detail.data,
    }
    const parsedDetail = orderDetailSchema.safeParse(orderDetail)
    expect(parsedDetail.success).toBe(true)
    expect(parsedDetail.success && parsedDetail.data.invoice?.number).toBe('СЧ-2026-000042')

    // В коллекции — только {id, number, status}, без сумм и PDF (§6).
    const summary = orderSummarySchema.safeParse({
      ...apiFixture('order_list_page.json').data[0],
      invoice: { id: invoiceId, number: 'СЧ-2026-000042', status: 'ISSUED' },
    })
    expect(summary.success).toBe(true)

    const invalid = orderSummarySchema.safeParse({
      ...apiFixture('order_list_page.json').data[0],
      invoice: { id: invoiceId, number: 'СЧ-2026-000042', status: 'ISSUED', total: 'oops' },
    })
    expect(invalid.success).toBe(false)
  })

  it('keeps the invoice block optional for deployments without an invoice yet', () => {
    // Бэкенд без счёта не обязана присылать ключ вообще (§6, invoice nullable).
    const withoutInvoice = apiFixture('order_detail_success.json').data
    const parsed = orderDetailSchema.safeParse(withoutInvoice)
    expect(parsed.success).toBe(true)
    expect(parsed.success && parsed.data.invoice).toBeUndefined()
  })
})

describe('invoice status presentation', () => {
  it('maps every contract status to a Russian label', () => {
    expect(INVOICE_STATUS_META.ISSUED.label).toBe('Выставлен')
    expect(INVOICE_STATUS_META.PAID.label).toBe('Оплачен')
    expect(INVOICE_STATUS_META.CANCELLED.label).toBe('Отменён')
    expect(INVOICE_STATUS_OPTIONS.map((option) => option.value)).toEqual([
      'ISSUED',
      'PAID',
      'CANCELLED',
    ])
  })

  it('maps every PDF state to a Russian label, PENDING included', () => {
    expect(INVOICE_PDF_STATUS_META.PENDING.label).toBe('Готовится')
    expect(INVOICE_PDF_STATUS_META.READY.label).toBe('Готов')
    expect(INVOICE_PDF_STATUS_META.FAILED.label).toBe('Ошибка рендера')
  })

  it('rejects a status outside the contract enum at the patch boundary', () => {
    expect(invoiceStatusPatchSchema.safeParse({ status: 'PAID' }).success).toBe(true)
    expect(invoiceStatusPatchSchema.safeParse({ status: 'REFUNDED' }).success).toBe(false)
    expect(invoiceStatusPatchSchema.safeParse({ status: 'PAID', version: 2 }).success).toBe(false)
  })
})

describe('invoice file name', () => {
  it('keeps the printed Cyrillic number as the file name', () => {
    expect(invoiceFileName('СЧ-2026-000042')).toBe('СЧ-2026-000042.pdf')
  })

  it.each([
    ['../../etc/passwd', 'etc_passwd.pdf'],
    ['счёт/2026', 'счёт_2026.pdf'],
    ['СЧ 2026 000042', 'СЧ_2026_000042.pdf'],
    ['<script>.pdf', 'script_pdf.pdf'],
  ])('sanitizes %s into %s', (input, expected) => {
    expect(invoiceFileName(input)).toBe(expected)
  })

  it('falls back to invoice.pdf for an empty or fully stripped name', () => {
    expect(invoiceFileName('')).toBe('invoice.pdf')
    expect(invoiceFileName('///')).toBe('invoice.pdf')
  })
})

describe('invoice repository', () => {
  it('issues an invoice for an order with an Idempotency-Key header', async () => {
    const { requester, requests } = requestSequence([{ body: fixture('invoice.json') }])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    const invoice = await repository.issueForOrder(orderId, 'key-42')

    expect(requests[0]?.url).toBe(`/api/v2/manager/orders/${orderId}/invoice`)
    expect(requests[0]?.options.method).toBe('POST')
    expect(headersOf(requests[0]?.options ?? {})['Idempotency-Key']).toBe('key-42')
    expect(invoice.number).toBe('СЧ-2026-000042')
  })

  it('reads the invoice by order and surfaces the 404 as a problem', async () => {
    const { requester, requests } = requestSequence([{ body: fixture('invoice.json') }])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    const invoice = await repository.getByOrder(orderId)
    expect(requests[0]?.url).toBe(`/api/v2/orders/${orderId}/invoice`)
    expect(invoice.id).toBe(invoiceId)

    const missing = requestSequence([
      {
        error: problemResponse(
          404,
          'INVOICE_NOT_FOUND',
          'Счёт не найден',
          'Счёт по заказу не выставлен',
        ),
      },
    ])
    const failing = createInvoiceRepository(
      createApiV2Client(missing.requester),
      recordingPdf(),
    )
    await expect(failing.getByOrder(orderId)).rejects.toMatchObject({
      code: 'INVOICE_NOT_FOUND',
      status: 404,
    })
  })

  it('sends If-Match with the invoice version on a status change', async () => {
    const { requester, requests } = requestSequence([{ body: fixture('invoice.json') }])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    await repository.changeStatus(invoiceId, 'PAID', 4)

    expect(requests[0]?.url).toBe(`/api/v2/manager/invoices/${invoiceId}`)
    expect(requests[0]?.options.method).toBe('PATCH')
    expect(headersOf(requests[0]?.options ?? {})['If-Match']).toBe('"4"')
    expect(requests[0]?.options.body).toEqual({ status: 'PAID' })
  })

  it('keeps a stale version readable as STALE_RESOURCE_VERSION', async () => {
    const { requester } = requestSequence([
      {
        error: problemResponse(
          409,
          'STALE_RESOURCE_VERSION',
          'Ресурс изменился',
          'Версия счёта устарела',
        ),
      },
    ])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    await expect(repository.changeStatus(invoiceId, 'PAID', 1)).rejects.toMatchObject({
      code: 'STALE_RESOURCE_VERSION',
      status: 409,
    })
  })

  it('normalizes If-Match to a quoted entity tag', () => {
    expect(toIfMatch(7)).toBe('"7"')
    expect(toIfMatch('7')).toBe('"7"')
    expect(toIfMatch('"7"')).toBe('"7"')
  })

  it('regenerates the PDF and reads bytes on the dedicated download path', async () => {
    const { requester, requests } = requestSequence([{ body: fixture('invoice.json') }])
    const pdf = recordingPdf()
    const repository = createInvoiceRepository(createApiV2Client(requester), pdf)

    await repository.regeneratePdf(invoiceId)
    expect(requests[0]?.url).toBe(`/api/v2/manager/invoices/${invoiceId}/pdf`)
    expect(requests[0]?.options.method).toBe('POST')

    await repository.downloadPdf(invoiceId, invoiceFileName('СЧ-2026-000042'))
    // PDF выдаётся байтами по отдельному маршруту, JSON-клиент его не качает.
    expect(pdf.fetched).toEqual([`/api/v2/orders/invoices/${invoiceId}/download`])
    expect(pdf.saved).toEqual([{ name: 'СЧ-2026-000042.pdf', size: 16 }])
  })

  it('saves organization requisites with If-Match on the organization version', async () => {
    const detail = fixture('organization-detail.json')
    const { requester, requests } = requestSequence([{ body: detail }])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    const updated = await repository.updateOrganizationRequisites(
      organizationId,
      {
        taxId: '191234567',
        legalAddress: '220030, г. Минск, ул. Ленина, 1',
        legalPhone: '+375 17 300 11 22',
        legalEmail: 'office@promelectro.by',
        bankName: 'ОАО «Бебанк»',
        bankCode: 'BYNORBY2',
        bankAccount: 'BY11NBRB00000000000000000933',
        version: 3,
      },
      3,
    )

    expect(requests[0]?.url).toBe(`/api/v2/manager/organizations/${organizationId}`)
    expect(requests[0]?.options.method).toBe('PATCH')
    expect(headersOf(requests[0]?.options ?? {})['If-Match']).toBe('"3"')
    expect(updated.bankAccount).toBe('BY11NBRB00000000000000000933')
  })

  it('parses an organization detail response with the invoice requisites', () => {
    const parsed = organizationDetailResponseSchema.parse(fixture('organization-detail.json'))
    expect(parsed.data).toMatchObject({
      taxId: '191234567',
      bankCode: 'BYNORBY2',
      version: 3,
    })
  })

  it('rejects unknown and non-string requisite keys at the patch boundary', () => {
    // Схема строгая, как и остальные на границе API: лишний ключ — ошибка,
    // а не «тихое» отсечение, иначе опечатка в разметке уехала бы на бэк.
    expect(() =>
      organizationRequisitesPatchSchema.parse({ taxId: '191234567', unp: 'дубль' }),
    ).toThrow()
    expect(organizationRequisitesPatchSchema.safeParse({ taxId: 191234567 }).success).toBe(false)
    expect(organizationRequisitesPatchSchema.safeParse({ taxId: null }).success).toBe(true)
  })

  it('rejects invalid identity before issuing a request', async () => {
    const { requester, requests } = requestSequence([])
    const repository = createInvoiceRepository(createApiV2Client(requester), recordingPdf())

    await expect(repository.getByOrder('not-a-uuid')).rejects.toThrow()
    await expect(repository.changeStatus('nope', 'PAID', 1)).rejects.toThrow()
    expect(requests).toHaveLength(0)
  })
})

describe('problemMessage', () => {
  it('prefers the Problem Details text over the fallback', () => {
    const problem = new AppProblem({
      code: 'ORDER_NOT_INVOICABLE',
      status: 409,
      message: 'По заказу нельзя выставить счёт',
      isProblemDetails: true,
      retryable: false,
    })
    expect(problemMessage(problem, 'Не удалось выставить счёт')).toBe(
      'По заказу нельзя выставить счёт',
    )
  })

  it('falls back for an error without problem details', () => {
    expect(problemMessage(new Error('boom'), 'Не удалось выставить счёт')).toBe(
      'Не удалось выставить счёт',
    )
  })
})
