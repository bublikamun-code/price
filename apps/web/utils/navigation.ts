const MALFORMED_PERCENT_ESCAPE = /%(?![0-9a-f]{2})/i

function containsControlCharacterOrBackslash(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0
    if (
      codePoint <= 0x1f
      || (codePoint >= 0x7f && codePoint <= 0x9f)
      || character === '\\'
    ) {
      return true
    }
  }
  return false
}

function isSafeRootRelativePath(value: string): boolean {
  if (
    !value.startsWith('/')
    || value.startsWith('//')
    || containsControlCharacterOrBackslash(value)
    || MALFORMED_PERCENT_ESCAPE.test(value)
  ) {
    return false
  }

  // Check more than one decoding layer so encoded separators cannot become an
  // absolute/protocol-relative URL after a downstream consumer decodes them.
  let decoded = value
  for (let depth = 0; depth < 5; depth += 1) {
    let next: string
    try {
      next = decodeURIComponent(decoded)
    } catch {
      return false
    }

    if (
      !next.startsWith('/')
      || next.startsWith('//')
      || containsControlCharacterOrBackslash(next)
    ) {
      return false
    }

    if (next === decoded) return true
    decoded = next
  }

  // More than five encoding layers is malformed for a navigation destination.
  return false
}

/**
 * Returns a same-site path suitable for client-side navigation.
 * Safe for SSR because it does not access browser globals or mutable state.
 */
export function getSafeRedirectPath(value: unknown, fallback: string): string {
  if (typeof value === 'string' && isSafeRootRelativePath(value)) {
    return value
  }
  return isSafeRootRelativePath(fallback) ? fallback : '/'
}
