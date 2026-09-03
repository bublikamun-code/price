// Развёртывание конверта ответа API: {"data": X} → X (§6 формат ответов).
// Некоторые эндпоинты отдают плоское тело — тогда payload возвращается как есть.

/** Если payload — конверт {"data": …} с непустым data, вернуть data; иначе payload. */
export function unwrapData<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    const inner = (payload as { data?: T | null }).data
    if (inner !== undefined && inner !== null) return inner
  }
  return payload as T
}
