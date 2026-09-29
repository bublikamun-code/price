import { z } from 'zod'
import { dateSchema, uuidSchema } from './common.schema'
import { responseMetaSchema } from './session.schema'

export const documentTypeSchema = z.enum(['CERTIFICATE', 'DATASHEET'])
export const documentScopeSchema = z.enum(['product', 'series'])

/**
 * Документ карточки товара (§16 п.38, apps/api/app/schemas/v2/documents.py).
 * Просроченный документ приходит с `isExpired: true` — помечается, а не скрывается.
 */
export const productDocumentSchema = z
  .object({
    id: uuidSchema,
    type: documentTypeSchema,
    fileName: z.string().min(1).max(512),
    scope: documentScopeSchema,
    validUntil: dateSchema.nullable(),
    isExpired: z.boolean(),
  })
  .strict()

export const productDocumentResponseSchema = z
  .object({
    data: productDocumentSchema,
    meta: responseMetaSchema,
  })
  .strict()

// DELETE /api/v2/manager/documents/{id} → 204 No Content: ofetch возвращает
// пустую строку (или undefined), валидируем отсутствие тела.
export const documentDeleteResponseSchema = z.union([z.null(), z.undefined(), z.literal('')])

export type DocumentType = z.infer<typeof documentTypeSchema>
export type DocumentScope = z.infer<typeof documentScopeSchema>
export type ProductDocument = z.infer<typeof productDocumentSchema>
export type ProductDocumentResponse = z.infer<typeof productDocumentResponseSchema>

/** Тело multipart-загрузки: PDF-файл + тип + опциональный срок (YYYY-MM-DD). */
export interface DocumentUploadInput {
  file: File
  type: DocumentType
  validUntil?: string | null
}
