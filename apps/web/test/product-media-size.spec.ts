import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { mainPhotoSrc } from '../utils/product-media'

// Аудит L13: мобильная карточка грузила крупный кадр 1200×1200. По
// конвенции §16 п.17 рядом лежит миниатюра 400×400 (`_thumb.webp`), в
// v2-контракте — URL с `?size=thumb`. Мобильная карточка должна брать
// миниатюру, десктопная — по-прежнему полный кадр в большом окне галереи.

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (relativePath: string) => readFileSync(resolve(webRoot, relativePath), 'utf8')

const mobileCard = read('pages/m/catalog/[sku].vue')
const desktopCard = read('pages/catalog/[sku].vue')

const FULL = '/api/v1/files/photo?key=photos-product%2Fp1%2Faaaaaaaa.webp'
const THUMB = '/api/v1/files/photo?key=photos-product%2Fp1%2Faaaaaaaa_thumb.webp'

describe('mainPhotoSrc: выбор размера главного кадра', () => {
  it('по умолчанию отдаёт миниатюру 400×400', () => {
    expect(mainPhotoSrc({ url: FULL, thumbUrl: THUMB }, new Set())).toBe(THUMB)
  })

  it('без миниатюры (совпадает с полным кадром) берёт полный кадр', () => {
    expect(mainPhotoSrc({ url: FULL, thumbUrl: FULL }, new Set())).toBe(FULL)
  })

  it('упавшая миниатюра откатывается на полный кадр', () => {
    const failed = new Set([THUMB])
    expect(mainPhotoSrc({ url: FULL, thumbUrl: THUMB }, failed)).toBe(FULL)
  })

  it('упавшие обе версии — заглушка (null), а не битая картинка', () => {
    const failed = new Set([THUMB, FULL])
    expect(mainPhotoSrc({ url: FULL, thumbUrl: THUMB }, failed)).toBeNull()
  })

  it('нет фото — тоже null', () => {
    expect(mainPhotoSrc(null, new Set())).toBeNull()
    expect(mainPhotoSrc(undefined, new Set())).toBeNull()
  })
})

describe('мобильная карточка: главный кадр — миниатюра (L13)', () => {
  it('главный <img> берёт src из activePhotoSrc, а не полный кадр', () => {
    expect(mobileCard).toContain('const activePhotoSrc = computed(() => mainPhotoSrc(activePhoto.value, failedMain))')
    expect(mobileCard).toContain(':src="activePhotoSrc"')
    // Полный кадр напрямую в <img> главного изображения не подставляется.
    expect(mobileCard).not.toContain(':src="activePhoto.url"')
  })

  it('кадры галереи хранят и полный кадр, и миниатюру', () => {
    expect(mobileCard).toContain('thumbUrl: thumbOf(p.photo_key) ?? main')
    expect(mobileCard).toContain('thumbUrl: thumbOf(key) ?? url')
    expect(mobileCard).toContain('const { photoOf, urlOf, thumbOf } = useProductPhoto()')
  })

  it('превью в галерее остаётся миниатюрой', () => {
    expect(mobileCard).toContain(':src="frame.thumbUrl"')
    expect(mobileCard).toContain('v-if="!failedThumbs.has(frame.thumbUrl)"')
  })
})

describe('десктопная карточка не сломана', () => {
  it('большое окно галереи по-прежнему показывает полный кадр', () => {
    expect(desktopCard).toContain('const activeMediaLarge = computed(() => {')
    expect(desktopCard).toContain('size=thumb')
  })

  it('превью десктопной галереи — миниатюра', () => {
    expect(desktopCard).toContain('const galleryThumbs = computed(')
    expect(desktopCard).toContain('size=thumb')
  })
})
