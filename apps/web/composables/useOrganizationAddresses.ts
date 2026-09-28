import type {
  OrganizationAddress,
  OrganizationAddressCreate,
} from '~/domain/api/v2/organizations.schema'
import { AppProblem } from '~/domain/api/v2/problem'
import { createOrganizationRepository } from '~/domain/organization/organization.repository'

/**
 * Адресная книга организации для оформления заявок. Эндпоинты v2 `/me/...`
 * резолвят организацию из сессии, поэтому composable лишь проверяет контекст
 * (паттерн useCartV2/useOrdersV2) и делегирует репозиторию.
 */
export function useOrganizationAddresses() {
  const auth = useAuth()
  const sessionContext = useSessionContext()
  const repository = createOrganizationRepository(useApiV2())

  async function ensureContextReady() {
    const userId = auth.user?.id
    if (!userId) return null

    const session = await sessionContext.ensureLoaded()
    if (!session || session.context.user.id !== userId) return null
    return session.context
  }

  /**
   * Сохранённые адреса активной организации. У пользователя без организации
   * бэкенд гарантирует пустой список; недоступный контекст даёт тот же
   * результат, чтобы checkout деградировал к текущему поведению.
   */
  async function listAddresses(): Promise<OrganizationAddress[]> {
    const context = await ensureContextReady()
    if (!context) return []
    return (await repository.listAddresses()).addresses
  }

  async function createAddress(
    payload: OrganizationAddressCreate,
  ): Promise<OrganizationAddress> {
    const context = await ensureContextReady()
    if (!context) {
      throw new AppProblem({
        code: 'AUTHENTICATION_REQUIRED',
        message: 'Не удалось определить организацию для адресной книги',
        isProblemDetails: false,
        retryable: false,
      })
    }
    const idempotencyKey = crypto.randomUUID()
    return (await repository.createAddress(payload, idempotencyKey)).address
  }

  return {
    listAddresses,
    createAddress,
  }
}
