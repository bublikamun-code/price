import { z } from 'zod'

const uuid = z.string().uuid()
const currency = z.string().regex(/^[A-Z]{3}$/)

export const responseMetaSchema = z.object({
  requestId: z.string().min(1),
})

export const currentUserSchema = z.object({
  id: uuid,
  email: z.string().email(),
  fullName: z.string(),
  role: z.enum(['CLIENT', 'MANAGER', 'ADMIN']),
  isActive: z.boolean(),
  displayCurrency: currency,
  consentAccepted: z.boolean(),
  totpEnabled: z.boolean(),
  priceDigestEnabled: z.boolean(),
  priceDigestSources: z.array(z.string()),
  forcePasswordChange: z.boolean(),
  phone: z.string().nullable(),
  legacyCompany: z.string().nullable(),
})

export const organizationMembershipSchema = z.object({
  organizationId: uuid,
  legalName: z.string(),
  displayName: z.string().nullable(),
  role: z.string().min(1),
  status: z.string().min(1),
  isPrimary: z.boolean(),
})

export const sessionContextSchema = z.object({
  user: currentUserSchema,
  commercialScope: z.enum(['USER', 'ORGANIZATION']),
  organizationId: uuid.nullable(),
  memberships: z.array(organizationMembershipSchema),
})

export const sessionResponseSchema = z.object({
  data: sessionContextSchema,
  meta: responseMetaSchema,
})

export type CurrentUser = z.infer<typeof currentUserSchema>
export type OrganizationMembership = z.infer<typeof organizationMembershipSchema>
export type SessionContext = z.infer<typeof sessionContextSchema>
export type SessionResponse = z.infer<typeof sessionResponseSchema>
