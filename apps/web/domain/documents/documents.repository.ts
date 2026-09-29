import type { ApiV2Client } from '../api/v2/client'
import { dateSchema, uuidSchema } from '../api/v2/common.schema'
import {
  documentDeleteResponseSchema,
  documentTypeSchema,
  productDocumentResponseSchema,
  type DocumentUploadInput,
  type ProductDocument,
} from '../api/v2/documents.schema'
import { createCatalogRepository } from '../catalog/catalog.repository'

/**
 * Документы товара/серии (§16 п.38, docs/API_V2_CONTRACT.md §8).
 * Загрузка/удаление — только MANAGER; скачивание байтами идёт мимо этого
 * репозитория (composables/useDocumentDownload.ts — там нужен blob, а не JSON).
 */
export interface DocumentsRepository {
  /** Документы карточки товара: свои и унаследованные из серии. */
  listForProduct(productId: string): Promise<ProductDocument[]>
  /**
   * Документы серии. Отдельного list-эндпоинта в контракте нет — документы
   * серии приходят только в product detail, поэтому берём detail первого
   * видимого товара серии и фильтруем scope=series.
   */
  listForSeries(seriesId: string): Promise<ProductDocument[]>
  uploadForProduct(productId: string, input: DocumentUploadInput): Promise<ProductDocument>
  uploadForSeries(seriesId: string, input: DocumentUploadInput): Promise<ProductDocument>
  remove(documentId: string): Promise<void>
}

function toFormData(input: DocumentUploadInput): FormData {
  const form = new FormData()
  form.append('file', input.file)
  form.append('type', documentTypeSchema.parse(input.type))
  const validUntil = input.validUntil?.trim() ?? ''
  if (validUntil) form.append('valid_until', dateSchema.parse(validUntil))
  return form
}

export function createDocumentsRepository(client: ApiV2Client): DocumentsRepository {
  const catalog = createCatalogRepository(client)

  async function upload(path: string, input: DocumentUploadInput): Promise<ProductDocument> {
    const response = await client.execute(path, productDocumentResponseSchema, {
      method: 'POST',
      body: toFormData(input),
    })
    return response.data.data
  }

  return {
    async listForProduct(productId) {
      const detail = await catalog.getById(uuidSchema.parse(productId))
      return detail.product.documents ?? []
    },
    async listForSeries(seriesId) {
      const id = uuidSchema.parse(seriesId)
      const page = await catalog.list({ series: [id], limit: 1, sort: 'sku' })
      if (!page.products.length) return []
      const detail = await catalog.getById(page.products[0].id)
      return (detail.product.documents ?? []).filter((doc) => doc.scope === 'series')
    },
    async uploadForProduct(productId, input) {
      return upload(`/api/v2/manager/products/${uuidSchema.parse(productId)}/documents`, input)
    },
    async uploadForSeries(seriesId, input) {
      return upload(`/api/v2/manager/series/${uuidSchema.parse(seriesId)}/documents`, input)
    },
    async remove(documentId) {
      await client.execute(
        `/api/v2/manager/documents/${uuidSchema.parse(documentId)}`,
        documentDeleteResponseSchema,
        { method: 'DELETE' },
      )
    },
  }
}
