import { afterEach, describe, expect, it, vi } from 'vitest'

import { useProductPhoto } from '../composables/useProductPhoto'

/** Подмена runtime-конфига: allowlist хостов приходит из NUXT_PUBLIC_IMAGE_ALLOWED_HOSTS. */
function withAllowedHosts(hosts: string[]): void {
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { imageAllowedHosts: hosts } }))
}

afterEach(() => vi.unstubAllGlobals())

describe('useProductPhoto', () => {
  it('routes S3 keys through the API redirect, escaping the key', () => {
    withAllowedHosts([])
    const { urlOf } = useProductPhoto()

    expect(urlOf('photos-series/serie-a.webp')).toBe(
      '/api/v1/files/photo?key=photos-series%2Fserie-a.webp',
    )
  })

  it('derives the thumb suffix for .webp keys', () => {
    withAllowedHosts([])
    const { thumbOf } = useProductPhoto()

    expect(thumbOf('photos-series/serie-a.webp')).toBe(
      '/api/v1/files/photo?key=photos-series%2Fserie-a_thumb.webp',
    )
    expect(thumbOf('photos-series/serie-a_thumb.webp')).toBe(
      '/api/v1/files/photo?key=photos-series%2Fserie-a_thumb.webp',
    )
  })

  it('drops external image URLs when the allowlist is empty', () => {
    // photo_key приходит из импортированной выгрузки поставщика: без
    // allowlist внешний URL превратился бы в маячок от имени посетителя.
    withAllowedHosts([])
    const { urlOf, thumbOf, photoOf } = useProductPhoto()

    expect(urlOf('https://tracker.example/pixel.gif')).toBeNull()
    expect(thumbOf('http://tracker.example/pixel.gif')).toBeNull()
    expect(photoOf({ photo_key: 'https://tracker.example/pixel.gif' })).toBeNull()
  })

  it('keeps external URLs from allowlisted hosts only, matched on exact host', () => {
    withAllowedHosts(['files.example.by'])
    const { urlOf } = useProductPhoto()

    expect(urlOf('https://files.example.by/photo.jpg')).toBe('https://files.example.by/photo.jpg')
    // поддомен, другой хост и похожий суффикс — не проходят
    expect(urlOf('https://evil-files.example.by/photo.jpg')).toBeNull()
    expect(urlOf('https://files.example.by.evil.com/photo.jpg')).toBeNull()
    expect(urlOf('https://other.example/photo.jpg')).toBeNull()
  })

  it('falls back to attributes.photo_url and still applies the allowlist', () => {
    withAllowedHosts(['files.example.by'])
    const { photoOf } = useProductPhoto()

    expect(photoOf({ photo_key: null, attributes: { photo_url: 'https://files.example.by/a.jpg' } })).toBe(
      'https://files.example.by/a.jpg',
    )
    expect(photoOf({ photo_key: null, attributes: { photo_url: 'https://evil.example/a.jpg' } })).toBeNull()
  })

  it('prefers photo_key over the attribute fallback', () => {
    withAllowedHosts([])
    const { photoOf } = useProductPhoto()

    expect(
      photoOf({
        photo_key: 'photos-series/a.webp',
        attributes: { photo_url: 'https://tracker.example/x.gif' },
      }),
    ).toBe('/api/v1/files/photo?key=photos-series%2Fa.webp')
  })

  it('returns null for missing keys and unparsable URLs', () => {
    withAllowedHosts(['files.example.by'])
    const { urlOf, thumbOf, photoOf } = useProductPhoto()

    expect(urlOf(null)).toBeNull()
    expect(urlOf(undefined)).toBeNull()
    expect(thumbOf(null)).toBeNull()
    expect(photoOf({ photo_key: null })).toBeNull()
    expect(urlOf('https://')).toBeNull()
  })
})
