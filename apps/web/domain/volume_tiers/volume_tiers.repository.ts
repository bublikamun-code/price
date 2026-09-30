import type { ApiV2Client } from '../api/v2/client'
import { uuidSchema } from '../api/v2/common.schema'
import { toIfMatch } from '../invoice/invoice.repository'
import {
  volumeTierCreateInputSchema,
  volumeTierDeleteResponseSchema,
  volumeTierListResponseSchema,
  volumeTierResponseSchema,
  volumeTierUpdateInputSchema,
  type VolumeTier,
  type VolumeTierCreateInput,
  type VolumeTierUpdateInput,
} from '../api/v2/volume_tiers.schema'

/**
 * Скидки за объём: CRUD лестницы бренда (§6, §16 п.41).
 *
 * Тонкая обёртка над v2: валидирует и то, что уходит, и то, что приходит,
 * и ничего не знает про UI. `If-Match` собирается из `version` ступени —
 * бэк не проставляет ETag-заголовок на этих эндпоинтах (§16 п.41 п.8), поэтому
 * версия живёт в теле ответа.
 *
 * Все операции — только для MANAGER/ADMIN: права проверяет `require_role`
 * на бэкенде, клиент лишь не показывает недоступные действия.
 */
export interface VolumeTiersRepository {
  /** Лестница бренда по возрастанию порога. */
  list(brandId: string): Promise<VolumeTier[]>
  create(brandId: string, input: VolumeTierCreateInput): Promise<VolumeTier>
  update(tierId: string, version: number, input: VolumeTierUpdateInput): Promise<VolumeTier>
  remove(tierId: string, version: number): Promise<void>
}

export function createVolumeTiersRepository(client: ApiV2Client): VolumeTiersRepository {
  return {
    async list(brandId) {
      const id = uuidSchema.parse(brandId)
      const response = await client.get(
        `/api/v2/manager/brands/${id}/volume-tiers`,
        volumeTierListResponseSchema,
      )
      return response.data
    },

    async create(brandId, input) {
      const id = uuidSchema.parse(brandId)
      const response = await client.execute(
        `/api/v2/manager/brands/${id}/volume-tiers`,
        volumeTierResponseSchema,
        { method: 'POST', body: volumeTierCreateInputSchema.parse(input) },
      )
      return response.data.data
    },

    async update(tierId, version, input) {
      const id = uuidSchema.parse(tierId)
      const response = await client.execute(`/api/v2/manager/volume-tiers/${id}`, volumeTierResponseSchema, {
        method: 'PATCH',
        body: volumeTierUpdateInputSchema.parse(input),
        headers: { 'If-Match': toIfMatch(version) },
      })
      return response.data.data
    },

    async remove(tierId, version) {
      const id = uuidSchema.parse(tierId)
      await client.execute(`/api/v2/manager/volume-tiers/${id}`, volumeTierDeleteResponseSchema, {
        method: 'DELETE',
        headers: { 'If-Match': toIfMatch(version) },
      })
    },
  }
}
