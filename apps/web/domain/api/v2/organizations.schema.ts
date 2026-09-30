import { z } from 'zod'
import { dateTimeSchema, uuidSchema } from './common.schema'

// Адресная книга организации (v2). Контракт: GET/POST /api/v2/me/organization/addresses,
// PATCH/DELETE .../{id} — клиентский UI правок адресов не использует, поэтому здесь
// только схемы чтения и создания. Ответы и тела — camelCase, envelope — strict.

export const organizationAddressKindSchema = z.enum(['LEGAL', 'DELIVERY', 'PICKUP'])

// Организация как её видит менеджер (§6 «Организации»): summary для коллекции
// и detail с печатными реквизитами для счёта (УНП = taxId, §16 п.40 п.4).
const organizationCountryCodeSchema = z.string().regex(/^[A-Z]{2}$/)

export const organizationSummarySchema = z
  .object({
    id: uuidSchema,
    legalName: z.string().min(1).max(255),
    displayName: z.string().min(1).max(255).nullable(),
    taxId: z.string().min(1).max(64).nullable(),
    countryCode: organizationCountryCodeSchema,
    defaultCurrency: z.string().regex(/^[A-Z]{3}$/),
    isActive: z.boolean(),
    version: z.number().int().min(1),
    createdAt: dateTimeSchema,
    updatedAt: dateTimeSchema,
  })
  .strict()

export const organizationDetailSchema = organizationSummarySchema
  .extend({
    legalAddress: z.string().min(1).max(2000).nullable(),
    legalEmail: z.string().min(1).max(320).nullable(),
    legalPhone: z.string().min(1).max(50).nullable(),
    bankName: z.string().min(1).max(255).nullable(),
    bankCode: z.string().min(1).max(64).nullable(),
    bankAccount: z.string().min(1).max(64).nullable(),
  })
  .strict()

const organizationResponseMetaSchema = z
  .object({
    requestId: z.string().min(1),
  })
  .strict()

export const organizationDetailResponseSchema = z
  .object({
    data: organizationDetailSchema,
    meta: organizationResponseMetaSchema,
  })
  .strict()

export const organizationListResponseSchema = z
  .object({
    data: z.array(organizationSummarySchema),
    meta: organizationResponseMetaSchema
      .extend({
        nextCursor: z.string().min(1).nullable(),
        hasMore: z.boolean(),
        limit: z.number().int().min(1).max(100),
        sort: z.string().min(1).max(32),
      })
      .strict(),
  })
  .strict()

export const organizationListQuerySchema = z
  .object({
    q: z.string().trim().min(1).max(255).optional(),
    sort: z
      .enum(['legalName', '-legalName', 'createdAt', '-createdAt'])
      .optional(),
    limit: z.number().int().min(1).max(100).optional(),
    cursor: z.string().max(4096).optional(),
  })
  .strict()

const organizationAddressMetaSchema = z
  .object({
    requestId: z.string().min(1),
  })
  .strict()

const optionalAddressTextSchema = (max: number) => z.string().max(max).nullish()

export const organizationAddressSchema = z
  .object({
    id: uuidSchema,
    kind: organizationAddressKindSchema,
    label: optionalAddressTextSchema(120),
    recipientName: optionalAddressTextSchema(255),
    phone: optionalAddressTextSchema(50),
    addressLine: z.string().min(1).max(500),
    city: optionalAddressTextSchema(120),
    postalCode: optionalAddressTextSchema(32),
    countryCode: z.string().regex(/^[A-Z]{2}$/),
    isDefault: z.boolean(),
    createdAt: dateTimeSchema,
  })
  .strict()

export const organizationAddressCreateSchema = z
  .object({
    kind: organizationAddressKindSchema,
    addressLine: z.string().trim().min(1).max(500),
    label: z.string().max(120).nullish(),
    recipientName: z.string().max(255).nullish(),
    phone: z.string().max(50).nullish(),
    city: z.string().max(120).nullish(),
    postalCode: z.string().max(32).nullish(),
    countryCode: z.string().regex(/^[A-Z]{2}$/).optional(),
    isDefault: z.boolean().optional(),
  })
  .strict()

export const organizationAddressResponseSchema = z
  .object({
    data: organizationAddressSchema,
    meta: organizationAddressMetaSchema,
  })
  .strict()

export const organizationAddressListResponseSchema = z
  .object({
    data: z.array(organizationAddressSchema),
    meta: organizationAddressMetaSchema,
  })
  .strict()

export type OrganizationAddressKind = z.infer<typeof organizationAddressKindSchema>
export type OrganizationSummary = z.infer<typeof organizationSummarySchema>
export type OrganizationDetail = z.infer<typeof organizationDetailSchema>
export type OrganizationResponse = z.infer<typeof organizationDetailResponseSchema>
export type OrganizationListResponse = z.infer<typeof organizationListResponseSchema>
export type OrganizationListQuery = z.infer<typeof organizationListQuerySchema>
export type OrganizationAddress = z.infer<typeof organizationAddressSchema>
export type OrganizationAddressCreate = z.infer<typeof organizationAddressCreateSchema>
export type OrganizationAddressResponse = z.infer<typeof organizationAddressResponseSchema>
export type OrganizationAddressListResponse = z.infer<typeof organizationAddressListResponseSchema>
