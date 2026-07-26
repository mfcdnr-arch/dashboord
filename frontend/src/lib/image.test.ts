import { describe, expect, it } from 'vitest'
import { dataUriBytes, scaledDimensions } from './image'

describe('scaledDimensions', () => {
  it('не меняет размеры, если укладываются в предел', () => {
    expect(scaledDimensions(300, 200, 512)).toEqual({ w: 300, h: 200 })
  })
  it('уменьшает по большей стороне с сохранением пропорций', () => {
    expect(scaledDimensions(1024, 512, 512)).toEqual({ w: 512, h: 256 })
  })
  it('масштабирует по высоте, если она больше', () => {
    expect(scaledDimensions(500, 2000, 512)).toEqual({ w: 128, h: 512 })
  })
  it('не даёт нулевых сторон', () => {
    const d = scaledDimensions(2000, 3, 512)
    expect(d.h).toBeGreaterThanOrEqual(1)
  })
  it('устойчив к нулевым исходным размерам', () => {
    expect(scaledDimensions(0, 0, 512)).toEqual({ w: 0, h: 0 })
  })
})

describe('dataUriBytes', () => {
  it('оценивает бинарный размер из base64 (~3/4 длины)', () => {
    // "AAAA" (4 base64-символа) → 3 байта
    expect(dataUriBytes('data:image/png;base64,AAAA')).toBe(3)
  })
  it('работает и без префикса data:', () => {
    expect(dataUriBytes('AAAAAAAA')).toBe(6)
  })
})
