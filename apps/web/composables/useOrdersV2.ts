import { nextTick } from "vue";
import type {
  OrderCreate,
  OrderDetail,
  OrderListQuery,
  OrderSummary,
} from "../domain/api/v2/order.schema";
import { AppProblem } from "../domain/api/v2/problem";
import { createOrderRepository } from "../domain/order/order.repository";
import type {
  OrderRepeatResult,
  OrderSnapshot,
} from "../domain/order/order.repository";
import { useCartV2 } from "./useCartV2";
import { useOrdersStore, type OrderOwner } from "../stores/orders";

interface ActiveOrderContext {
  user: { id: string };
  commercialScope: "USER" | "ORGANIZATION";
  organizationId: string | null;
}

function authenticationProblem(message: string): AppProblem {
  return new AppProblem({
    code: "AUTHENTICATION_REQUIRED",
    message,
    isProblemDetails: false,
    retryable: false,
  });
}

function scopeMismatch(): AppProblem {
  return new AppProblem({
    code: "ORDER_SCOPE_MISMATCH",
    status: 409,
    message: "Ответ заявки не соответствует активному коммерческому контексту",
    isProblemDetails: false,
    retryable: false,
  });
}

function ownerFromContext(context: ActiveOrderContext): OrderOwner {
  return {
    userId: context.user.id,
    commercialScope: context.commercialScope,
    organizationId: context.organizationId,
  };
}

function organizationMatchesContext(
  organizationId: string | null,
  context: ActiveOrderContext,
): boolean {
  return context.commercialScope === "USER"
    ? organizationId === null
    : organizationId === context.organizationId;
}

function orderMatchesContext(
  order: OrderSummary | OrderDetail,
  context: ActiveOrderContext,
): boolean {
  // Только организационный скоуп (Э6, §16 п.42): участники организации видят
  // заявки организации, в том числе инициированные другими (OWNER визирует
  // заявки BUYER). Требование initiatedByUserId === user.id делало такие
  // заявки недоступными списком/карточкой — ORDER_SCOPE_MISMATCH.
  return organizationMatchesContext(order.organizationId, context);
}

export function useOrdersV2() {
  const auth = useAuth();
  const sessionContext = useSessionContext();
  const store = useOrdersStore();
  const cart = useCartV2();
  const repository = createOrderRepository(useApiV2());

  async function ensureActiveContext(): Promise<ActiveOrderContext> {
    const userId = auth.user?.id;
    if (!userId) {
      store.reset();
      throw authenticationProblem(
        "Необходимо войти в аккаунт перед просмотром заявок",
      );
    }

    const session = await sessionContext.ensureLoaded();
    if (!session || session.context.user.id !== userId) {
      store.reset();
      throw authenticationProblem(
        "Не удалось определить коммерческий контекст заявки",
      );
    }

    // Scope changes invalidate the client stores. Wait for the plugin watcher
    // before starting a request against the newly resolved server context.
    await nextTick();
    return session.context;
  }

  function assertOrdersInContext(
    orders: Array<OrderSummary | OrderDetail>,
    context: ActiveOrderContext,
  ) {
    if (orders.some((order) => !orderMatchesContext(order, context))) {
      throw scopeMismatch();
    }
  }

  async function list(params: OrderListQuery = {}) {
    await ensureActiveContext();
    const result = await repository.list(params);
    const current = await ensureActiveContext();
    assertOrdersInContext(result.orders, current);
    return result;
  }

  async function getById(orderId: string): Promise<OrderSnapshot> {
    await ensureActiveContext();
    const result = await repository.getById(orderId);
    const current = await ensureActiveContext();
    assertOrdersInContext([result.order], current);
    return result;
  }

  async function cancel(orderId: string): Promise<OrderSnapshot> {
    await ensureActiveContext();
    const result = await repository.cancel(orderId);
    const current = await ensureActiveContext();
    assertOrdersInContext([result.order], current);
    return result;
  }

  // Виза владельца организации (Э6). Заявку мог инициировать другой участник
  // организации, поэтому проверяем только организационный скоуп — без
  // требования initiatedByUserId, как в assertOrdersInContext.
  async function approve(orderId: string): Promise<OrderSnapshot> {
    await ensureActiveContext();
    const result = await repository.approve(orderId);
    const current = await ensureActiveContext();
    if (!organizationMatchesContext(result.order.organizationId, current)) {
      throw scopeMismatch();
    }
    return result;
  }

  async function reject(orderId: string, reason: string): Promise<OrderSnapshot> {
    await ensureActiveContext();
    const result = await repository.reject(orderId, reason);
    const current = await ensureActiveContext();
    if (!organizationMatchesContext(result.order.organizationId, current)) {
      throw scopeMismatch();
    }
    return result;
  }

  async function repeat(
    orderId: string,
    orderVersion: number,
  ): Promise<OrderRepeatResult> {
    await ensureActiveContext();
    const result = await repository.repeat(orderId, `"${orderVersion}"`);

    // Keep the scoped v2 cart store aligned with the successful mutation. The
    // repeat itself remains successful if this best-effort refresh fails; the
    // destination cart performs its own request on mount.
    try {
      await cart.refresh();
    } catch {
      // Navigation below still lands on the authoritative cart page.
    }

    const current = await ensureActiveContext();
    if (!organizationMatchesContext(result.cart.organizationId, current)) {
      throw scopeMismatch();
    }
    return result;
  }

  async function submit(payload: OrderCreate) {
    const userId = auth.user?.id;
    if (!userId) {
      store.reset();
      throw authenticationProblem(
        "Необходимо войти в аккаунт перед созданием заявки",
      );
    }

    const session = await sessionContext.ensureLoaded();
    if (!session || session.context.user.id !== userId) {
      store.reset();
      throw authenticationProblem(
        "Не удалось определить коммерческий контекст заявки",
      );
    }
    await nextTick();
    await cart.ensureReady();
    const result = await store.submit(
      repository,
      ownerFromContext(session.context),
      payload,
    );

    try {
      await cart.refresh();
    } catch (cause) {
      store.setCartRefreshError(cause);
    }
    return result;
  }

  return {
    store,
    list,
    getById,
    cancel,
    approve,
    reject,
    repeat,
    submit,
    reset: () => store.reset(),
  };
}
