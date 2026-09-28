import { z } from 'zod'
import { dateTimeSchema, uuidSchema } from './common.schema'

// Адресная книга организации (v2). Контракт: GET/POST /api/v2/me/organization/addresses,
// PATCH/DELETE .../{id} — клиентский UI правок адресов не использует, поэтому здесь
// только схемы чтения и создания. Ответы и тела — camelCase, envelope — strict.

export const organizationAddressKindSchema = z.enum(['LEGAL', 'DELIVERY', 'PICKUP'])

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
export type OrganizationAddress = z.infer<typeof organizationAddressSchema>
export type OrganizationAddressCreate = z.infer<typeof organizationAddressCreateSchema>
export type OrganizationAddressResponse = z.infer<typeof organizationAddressResponseSchema>
export type OrganizationAddressListResponse = z.infer<typeof organizationAddressListResponseSchema>
