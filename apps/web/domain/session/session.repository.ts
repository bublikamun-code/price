import type { ApiV2Client } from '../api/v2/client'
import { sessionResponseSchema, type SessionContext } from '../api/v2/session.schema'

export interface SessionSnapshot {
  context: SessionContext
  requestId: string
}

export interface SessionRepository {
  getCurrent(): Promise<SessionSnapshot>
}

export function createSessionRepository(client: ApiV2Client): SessionRepository {
  return {
    async getCurrent() {
      const response = await client.get('/api/v2/session', sessionResponseSchema)
      return {
        context: response.data,
        requestId: response.meta.requestId,
      }
    },
  }
}
