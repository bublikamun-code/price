/**
 * Ключ идемпотентности для мутаций v2.
 *
 * `crypto.randomUUID()` существует только в secure-контекстах (HTTPS,
 * localhost) — на HTTP-стенде он undefined и фича падает до сети (вскрыто
 * GUI-обходом Э7). Фолбэк — v4-подобный UUID из Math.random: для
 * Idempotency-Key криптостойкость не требуется, важна уникальность.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const rand = (Math.random() * 16) | 0
    const value = char === 'x' ? rand : (rand & 0x3) | 0x8
    return value.toString(16)
  })
}
