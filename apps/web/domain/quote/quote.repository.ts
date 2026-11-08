import type { ApiV2Client, ApiResponse } from '../api/v2/client'
import { uuidSchema } from '../api/v2/common.schema'
import {
  quoteAcceptResponseSchema,
  quoteAcceptSchema,
  quoteCreateSchema,
  quoteDeleteResponseSchema,
  quoteEditSchema,
  quoteListQuerySchema,
  quoteListResponseSchema,
  quotePdfRenderResponseSchema,
  quoteResponseSchema,
  type QuoteAccept,
  type QuoteCreate,
  type QuoteEdit,
  type QuoteListQuery,
  type QuoteListResponse,
  type QuoteOut,
  type QuotePdfRender,
  type QuoteResponse,
} from '../api/v2/quote.schema'
import { toIfMatch } from '../invoice/invoice.repository'

/**
 * Коммерческие предложения (Э8): менеджерские операции (create/edit/send/
 * delete/PDF-рендер) и клиентские (лента org-scope, accept/reject, PDF
 * байтами).
 *
 * JSON-операции идут через ApiV2Client; PDF отдаётся **байтами** и в JSON
 * клиент не вписывается — транспорт для байтов и сохранение файла внедряются
 * (composables/useQuotes.ts), здесь остаётся только оркестровка. Паттерн —
 * domain/invoice/invoice.repository.ts.
 */
export type QuotePdfFetcher = (path: string) => Promise<Blob>
export type QuotePdfSaver = (blob: Blob, fileName: string) => void

export interface QuotePdfTransport {
  fetch: QuotePdfFetcher
  save: QuotePdfSaver
}

export interface QuotePage {
  quotes: QuoteListResponse['data']
  requestId: string
  nextCursor: string | null
  hasMore: boolean
  limit: number
  sort: 'createdAt,id'
}

export interface QuoteSnapshot {
  quote: QuoteOut
  requestId: string
}

export interface QuoteAcceptResult {
  orderId: string
  requestId: string
  idempotencyReplayed: boolean
}

export interface QuoteRepository {
  /** Лента КП менеджера (все организации, курсор + фильтр статуса). */
  listManager(params?: QuoteListQuery): Promise<QuotePage>
  /** Лента КП активной организации клиента (DRAFT скрыты). */
  listClient(params?: QuoteListQuery): Promise<QuotePage>
  /** Создать DRAFT. */
  create(payload: QuoteCreate): Promise<QuoteOut>
  getManager(quoteId: string): Promise<QuoteSnapshot>
  getClient(quoteId: string): Promise<QuoteSnapshot>
  /** Правка DRAFT (If-Match): замена позиций и/или validUntil. */
  edit(quoteId: string, payload: QuoteEdit, ifMatch: string | number): Promise<QuoteOut>
  /** Удалить DRAFT (If-Match) → 204. */
  remove(quoteId: string, ifMatch: string | number): Promise<void>
  /** DRAFT → SENT; без validUntil бэкенд вернёт 400. */
  send(quoteId: string, ifMatch: string | number): Promise<QuoteOut>
  /** Синхронный рендер PDF (повтор перерендеривает и подменяет файл). */
  renderPdf(quoteId: string): Promise<QuotePdfRender>
  /** Принять КП → заявка (1:1 идемпотентность по Idempotency-Key). */
  accept(
    quoteId: string,
    payload: QuoteAccept,
    idempotencyKey: string,
  ): Promise<QuoteAcceptResult>
  /** Отказаться от КП (SENT → REJECTED). */
  reject(quoteId: string): Promise<QuoteOut>
  /** Скачать PDF байтами (клиентский endpoint, никогда presigned — §16 п.37). */
  downloadPdf(quoteId: string, fileName: string): Promise<void>
}

function page(response: ApiResponse<QuoteListResponse>): QuotePage {
  return {
    quotes: response.data.data,
    requestId: response.data.meta.requestId,
    nextCursor: response.data.meta.nextCursor,
    hasMore: response.data.meta.hasMore,
    limit: response.data.meta.limit,
    sort: response.data.meta.sort,
  }
}

function snapshot(response: ApiResponse<QuoteResponse>): QuoteSnapshot {
  return {
    quote: response.data.data,
    requestId: response.data.meta.requestId,
  }
}

function listPath(base: '/api/v2/manager/quotes' | '/api/v2/quotes', params: QuoteListQuery = {}): string {
  const query = quoteListQuerySchema.parse(params)
  const search = new URLSearchParams()

  if (query.status) search.set('status', query.status)
  if (query.limit !== undefined) search.set('limit', String(query.limit))
  if (query.cursor !== undefined) search.set('cursor', query.cursor)

  const encoded = search.toString()
  return encoded ? `${base}?${encoded}` : base
}

export function createQuoteRepository(
  client: ApiV2Client,
  pdf: QuotePdfTransport,
): QuoteRepository {
  return {
    async listManager(params) {
      return client
        .execute(listPath('/api/v2/manager/quotes', params), quoteListResponseSchema, {
          method: 'GET',
        })
        .then(page)
    },
    async listClient(params) {
      return client
        .execute(listPath('/api/v2/quotes', params), quoteListResponseSchema, { method: 'GET' })
        .then(page)
    },
    async create(payload) {
      const response = await client.execute('/api/v2/manager/quotes', quoteResponseSchema, {
        method: 'POST',
        body: quoteCreateSchema.parse(payload),
      })
      return response.data.data
    },
    async getManager(quoteId) {
      return client
        .execute(`/api/v2/manager/quotes/${uuidSchema.parse(quoteId)}`, quoteResponseSchema, {
          method: 'GET',
        })
        .then(snapshot)
    },
    async getClient(quoteId) {
      return client
        .execute(`/api/v2/quotes/${uuidSchema.parse(quoteId)}`, quoteResponseSchema, {
          method: 'GET',
        })
        .then(snapshot)
    },
    async edit(quoteId, payload, ifMatch) {
      const response = await client.execute(
        `/api/v2/manager/quotes/${uuidSchema.parse(quoteId)}`,
        quoteResponseSchema,
        {
          method: 'PATCH',
          body: quoteEditSchema.parse(payload),
          headers: { 'If-Match': toIfMatch(ifMatch) },
        },
      )
      return response.data.data
    },
    async remove(quoteId, ifMatch) {
      await client.execute(
        `/api/v2/manager/quotes/${uuidSchema.parse(quoteId)}`,
        quoteDeleteResponseSchema,
        {
          method: 'DELETE',
          headers: { 'If-Match': toIfMatch(ifMatch) },
        },
      )
    },
    async send(quoteId, ifMatch) {
      const response = await client.execute(
        `/api/v2/manager/quotes/${uuidSchema.parse(quoteId)}/send`,
        quoteResponseSchema,
        {
          method: 'POST',
          headers: { 'If-Match': toIfMatch(ifMatch) },
        },
      )
      return response.data.data
    },
    async renderPdf(quoteId) {
      const response = await client.execute(
        `/api/v2/manager/quotes/${uuidSchema.parse(quoteId)}/pdf`,
        quotePdfRenderResponseSchema,
        { method: 'POST' },
      )
      return response.data.data
    },
    async accept(quoteId, payload, idempotencyKey) {
      const response = await client.execute(
        `/api/v2/quotes/${uuidSchema.parse(quoteId)}/accept`,
        quoteAcceptResponseSchema,
        {
          method: 'POST',
          body: quoteAcceptSchema.parse(payload),
          headers: { 'Idempotency-Key': idempotencyKey },
        },
      )
      return {
        orderId: response.data.data.id,
        requestId: response.data.meta.requestId,
        idempotencyReplayed: response.idempotencyReplayed,
      }
    },
    async reject(quoteId) {
      const response = await client.execute(
        `/api/v2/quotes/${uuidSchema.parse(quoteId)}/reject`,
        quoteResponseSchema,
        { method: 'POST' },
      )
      return response.data.data
    },
    async downloadPdf(quoteId, fileName) {
      const blob = await pdf.fetch(
        `/api/v2/quotes/${uuidSchema.parse(quoteId)}/pdf/download`,
      )
      pdf.save(blob, fileName)
    },
  }
}
