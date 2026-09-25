import { createApiV2Client } from '~/domain/api/v2/client'

export function useApiV2() {
  const { request } = useApi()
  return createApiV2Client(request)
}
