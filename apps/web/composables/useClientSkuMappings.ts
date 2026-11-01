import type {
  ClientSkuMapping,
  ClientSkuMappingCreate,
} from '~/domain/api/v2/client-sku.schema'
import { AppProblem, problemMessage, toAppProblem } from '~/domain/api/v2/problem'
import type { ApplyCsvResult } from '~/domain/client-sku/client-sku.repository'
import { createClientSkuRepository } from '~/domain/client-sku/client-sku.repository'
import { newIdempotencyKey } from '~/utils/idempotency-key'

export const ORGANIZATION_REQUIRED_MESSAGE =
  'Мои артикулы доступны только в контексте организации'

/** Человекочитаемый текст ошибки справочника: 422 ORGANIZATION_REQUIRED и
 * потерянный контекст сессии сводятся к одному понятному сообщению. */
export function clientSkuProblemMessage(cause: unknown, fallback: string): string {
  const problem = toAppProblem(cause, fallback)
  if (problem.code === 'ORGANIZATION_REQUIRED') return ORGANIZATION_REQUIRED_MESSAGE
  return problemMessage(cause, fallback)
}

export interface ClientSkuLoadOptions {
  /** Фильтр по клиентскому артикулу/примечанию (?query=). */
  query?: string
  /** Страница (по умолчанию 1). */
  page?: number
  /** Дописать результаты к текущему списку («Показать ещё»). */
  append?: boolean
  /**
   * Менеджерский скоуп: список конкретной организации. Без поля — клиентский
   * скоуп (активная организация из сессии).
   */
  organizationId?: string
}

/**
 * Кросс-справочник клиентских артикулов. Состояние списка живёт в экземпляре
 * composable (у страницы-менеджера и клиентского режима — свои экземпляры);
 * клиентские операции проверяют активную организацию (паттерн
 * useCartV2/useOrdersV2) и без неё не ходят в сеть.
 */
export function useClientSkuMappings() {
  const auth = useAuth()
  const sessionContext = useSessionContext()
  const cart = useCartV2()
  const repository = createClientSkuRepository(useApiV2())

  const mappings = ref<ClientSkuMapping[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref('')

  async function ensureActiveOrganization(): Promise<string> {
    const userId = auth.user?.id
    if (!userId) {
      throw new AppProblem({
        code: 'AUTHENTICATION_REQUIRED',
        message: 'Необходимо войти в аккаунт',
        isProblemDetails: false,
        retryable: false,
      })
    }

    const session = await sessionContext.ensureLoaded()
    if (!session || session.context.user.id !== userId) {
      throw new AppProblem({
        code: 'ORGANIZATION_REQUIRED',
        status: 422,
        message: ORGANIZATION_REQUIRED_MESSAGE,
        isProblemDetails: false,
        retryable: false,
      })
    }

    const organizationId = session.context.organizationId
    if (!organizationId) {
      throw new AppProblem({
        code: 'ORGANIZATION_REQUIRED',
        status: 422,
        message: ORGANIZATION_REQUIRED_MESSAGE,
        isProblemDetails: false,
        retryable: false,
      })
    }
    return organizationId
  }

  /** Страница справочника. Без organizationId — активная организация из сессии. */
  async function loadList(options: ClientSkuLoadOptions = {}) {
    if (loading.value) return null
    loading.value = true
    error.value = ''
    const targetPage = options.page ?? 1
    try {
      const params = { query: options.query, page: targetPage, pageSize: pageSize.value }
      const result = options.organizationId
        ? await repository.listForOrg(options.organizationId, params)
        : await repository.list(params)
      mappings.value = options.append
        ? [...mappings.value, ...result.mappings]
        : result.mappings
      total.value = result.total
      page.value = result.page
      pageSize.value = result.pageSize
      return result
    } catch (cause) {
      error.value = clientSkuProblemMessage(cause, 'Не удалось загрузить справочник')
      return null
    } finally {
      loading.value = false
    }
  }

  /** Создать связку. Без organizationId — активная организация из сессии. */
  async function create(
    payload: ClientSkuMappingCreate,
    organizationId?: string,
  ): Promise<ClientSkuMapping> {
    if (organizationId) {
      const result = await repository.createForOrg(organizationId, payload, newIdempotencyKey())
      return result.mapping
    }
    await ensureActiveOrganization()
    const result = await repository.create(payload, newIdempotencyKey())
    return result.mapping
  }

  /** Удалить связку. Без organizationId — активная организация из сессии. */
  async function remove(mappingId: string, organizationId?: string): Promise<void> {
    if (organizationId) {
      await repository.removeForOrg(organizationId, mappingId)
      return
    }
    await ensureActiveOrganization()
    await repository.remove(mappingId)
  }

  /**
   * Применить CSV-список клиентских артикулов (только активная организация).
   * Бэк сам добавляет найденные позиции в заявку, поэтому после успеха
   * принудительно перечитываем корзину (ETag уже устарел).
   */
  async function applyCsv(csv: string): Promise<ApplyCsvResult> {
    await ensureActiveOrganization()
    const result = await repository.applyCsv(csv)
    // Обновление корзины — best-effort: отчёт применения остаётся валидным,
    // даже если перечитать не удалось (корзина перечитается на переходе).
    try {
      await cart.refresh()
    } catch {
      // Корзина догрузится сама на следующем обращении.
    }
    return result
  }

  return {
    mappings,
    total,
    page,
    pageSize,
    loading,
    error,
    loadList,
    create,
    remove,
    applyCsv,
  }
}
