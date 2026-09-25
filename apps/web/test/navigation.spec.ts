import { describe, expect, it } from 'vitest'

import { getSafeRedirectPath } from '../utils/navigation'

describe('getSafeRedirectPath', () => {
  it.each([
    ['/dashboard'],
    ['/catalog?category=valves#details'],
    ['/orders/42?tab=history'],
    ['/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3'],
    ['/?next=%2Fdashboard'],
  ])('accepts root-relative same-site path %s', (value) => {
    expect(getSafeRedirectPath(value, '/fallback')).toBe(value)
  })

  it.each([
    ['an absolute URL', 'https://evil.example/path'],
    ['a custom-scheme URL', 'javascript:alert(1)'],
    ['a protocol-relative URL', '//evil.example/path'],
    ['a backslash path', '/\\evil.example/path'],
    ['an encoded backslash', '/%5Cevil.example/path'],
    ['a multi-encoded backslash', '/%255Cevil.example/path'],
    ['a control character', '/dashboard\n'],
    ['a NUL character', '/dashboard\u0000'],
    ['a DEL character', '/dashboard\u007f'],
    ['a malformed escape', '/dashboard/%'],
    ['a non-root-relative path', 'dashboard'],
    ['a dot path', './dashboard'],
    ['a parent path', '../dashboard'],
    ['an empty path', ''],
  ])('rejects %s and uses the fallback', (_name, value) => {
    expect(getSafeRedirectPath(value, '/fallback')).toBe('/fallback')
  })

  it.each([undefined, null, 42, {}, ['/dashboard']])(
    'rejects non-string value %j and uses the fallback',
    (value) => {
      expect(getSafeRedirectPath(value, '/fallback')).toBe('/fallback')
    },
  )

  it('uses root when the fallback is also unsafe', () => {
    expect(getSafeRedirectPath('https://evil.example', '//evil.example')).toBe('/')
  })
})
