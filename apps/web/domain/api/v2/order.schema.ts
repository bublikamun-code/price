import { z } from "zod";
import { cartResponseSchema } from "./cart.schema";
import {
  dateSchema,
  dateTimeSchema,
  maxDatabaseInteger,
  moneySchema,
  quantitySchema,
  rateSchema,
  uuidSchema,
} from "./common.schema";
import { invoiceSchema, invoiceSummarySchema } from "./invoice.schema";

const noteSchema = z.string().max(2000).nullable().optional();

const orderResponseMetaSchema = z
  .object({
    requestId: z.string().min(1),
  })
  .strict();

const orderDateSchema = dateSchema.refine((value) => {
  if (value < "0001-01-01") return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return (
    !Number.isNaN(parsed.valueOf()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}, "Date must be a valid calendar date");

export const orderItemCreateSchema = z
  .object({
    productId: uuidSchema,
    quantity: quantitySchema,
    note: noteSchema,
  })
  .strict();

export const orderDeliveryCreateSchema = z
  .object({
    method: z.enum(["PICKUP", "DELIVERY"]),
    addressId: uuidSchema.nullable().optional(),
    contactName: z.string().max(255).nullable().optional(),
    phone: z.string().max(50).nullable().optional(),
    preferredDate: orderDateSchema.nullable().optional(),
    comment: z.string().max(2000).nullable().optional(),
  })
  .strict();

export const orderCreateSchema = z
  .object({
    draftId: uuidSchema.nullable().optional(),
    items: z.array(orderItemCreateSchema).min(1).max(500),
    delivery: orderDeliveryCreateSchema,
  })
  .strict()
  .superRefine((payload, context) => {
    const seen = new Set<string>();
    payload.items.forEach((item, index) => {
      if (seen.has(item.productId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["items", index, "productId"],
          message: "Duplicate productId values are not allowed",
        });
      }
      seen.add(item.productId);
    });
  });

const orderSearchQuerySchema = z.string().trim().min(1).max(255);

const orderTotalBoundSchema = z
  .string()
  .regex(/^\d{1,12}(\.\d{1,2})?$/, "Total bound must be a decimal amount string");

export const orderListQuerySchema = z
  .object({
    status: z
      .enum(["NEW", "IN_PROGRESS", "SHIPPED", "COMPLETED", "CANCELLED"])
      .optional(),
    q: orderSearchQuerySchema.optional(),
    dateFrom: orderDateSchema.optional(),
    dateTo: orderDateSchema.optional(),
    minTotal: orderTotalBoundSchema.optional(),
    maxTotal: orderTotalBoundSchema.optional(),
    limit: z.number().int().min(1).max(100).optional(),
    cursor: z.string().max(4096).optional(),
  })
  .strict();

export const orderStatusSchema = z.enum([
  "NEW",
  "IN_PROGRESS",
  "SHIPPED",
  "COMPLETED",
  "CANCELLED",
]);

export const orderSummarySchema = z
  .object({
    id: uuidSchema,
    sequence: z.number().int().nullable(),
    organizationId: uuidSchema.nullable(),
    initiatedByUserId: uuidSchema,
    status: orderStatusSchema,
    total: moneySchema,
    exchangeRate: rateSchema,
    createdAt: dateTimeSchema,
    updatedAt: dateTimeSchema,
    version: z.number().int().min(1),
    // Блок счёта в коллекции — сокращённый (§6 «Счета на оплату»): номер и
    // статус, сумма и PDF здесь не выводятся.
    invoice: invoiceSummarySchema.nullable().optional(),
  })
  .strict();

export const orderLineSchema = z
  .object({
    id: uuidSchema,
    productId: uuidSchema.nullable(),
    sku: z.string().nullable(),
    name: z.string().nullable(),
    quantity: z.number().int().min(1).max(maxDatabaseInteger),
    unitPrice: moneySchema,
    lineTotal: moneySchema,
    note: z.string().nullable(),
  })
  .strict();

export const orderDeliverySummarySchema = z
  .object({
    method: z.enum(["PICKUP", "DELIVERY"]),
    pickupPoint: z.string().nullable(),
    addressId: uuidSchema.nullable(),
    address: z.string().nullable(),
    contactName: z.string().nullable(),
    phone: z.string().nullable(),
    preferredDate: orderDateSchema.nullable(),
    comment: z.string().nullable(),
  })
  .strict();

export const orderDetailSchema = z
  .object({
    id: uuidSchema,
    sequence: z.number().int().nullable(),
    organizationId: uuidSchema.nullable(),
    initiatedByUserId: uuidSchema,
    managerId: uuidSchema.nullable(),
    status: orderStatusSchema,
    total: moneySchema,
    exchangeRate: rateSchema,
    lines: z.array(orderLineSchema),
    delivery: orderDeliverySummarySchema,
    notes: z.string().nullable(),
    createdAt: dateTimeSchema,
    updatedAt: dateTimeSchema,
    version: z.number().int().min(1),
    // Полный блок счёта в деталях заказа; счёта нет — null (§6).
    invoice: invoiceSchema.nullable().optional(),
  })
  .strict();

export const orderListResponseSchema = z
  .object({
    data: z.array(orderSummarySchema),
    meta: z
      .object({
        requestId: z.string().min(1),
        nextCursor: z.string().min(1).nullable(),
        hasMore: z.boolean(),
        limit: z.number().int().min(1).max(100),
        sort: z.literal("createdAt,id"),
      })
      .strict(),
  })
  .strict();

export const orderResponseSchema = z
  .object({
    data: orderDetailSchema,
    meta: orderResponseMetaSchema,
  })
  .strict();

export const orderRepeatResponseSchema = cartResponseSchema;

export type OrderItemCreate = z.infer<typeof orderItemCreateSchema>;
export type OrderDeliveryCreate = z.infer<typeof orderDeliveryCreateSchema>;
export type OrderCreate = z.infer<typeof orderCreateSchema>;
export type OrderListQuery = z.infer<typeof orderListQuerySchema>;
export type OrderStatus = z.infer<typeof orderStatusSchema>;
export type OrderSummary = z.infer<typeof orderSummarySchema>;
export type OrderLine = z.infer<typeof orderLineSchema>;
export type OrderDeliverySummary = z.infer<typeof orderDeliverySummarySchema>;
export type OrderDetail = z.infer<typeof orderDetailSchema>;
export type OrderListResponse = z.infer<typeof orderListResponseSchema>;
export type OrderResponse = z.infer<typeof orderResponseSchema>;
export type OrderRepeatResponse = z.infer<typeof orderRepeatResponseSchema>;
