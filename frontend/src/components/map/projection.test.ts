import { describe, expect, it } from 'vitest'
import { boundsOf, esc, px, py, ringPath, shortName } from './projection'

describe('проекция карты', () => {
  it('сжимает долготу по широте региона, широта растёт вверх', () => {
    // Один градус долготы на широте 48° короче градуса широты — иначе
    // республика на карте выглядела бы растянутой поперёк.
    expect(px(1)).toBeLessThan(1000)
    expect(px(1)).toBeGreaterThan(600)
    // Экранная ось Y направлена вниз, географическая широта — вверх.
    expect(py(48)).toBeLessThan(py(47))
  })

  it('габариты контура берут запас по краям', () => {
    const ring = [[37, 47], [39, 47], [39, 49], [37, 49]]
    const b = boundsOf(ring, 0.05)
    const xs = ring.map((p) => px(p[0]))
    expect(b.x).toBeLessThan(Math.min(...xs))
    expect(b.x + b.w).toBeGreaterThan(Math.max(...xs))
  })

  it('путь замкнут и содержит все точки', () => {
    const d = ringPath([[37, 47], [38, 48]])
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d.split('L').length).toBe(2)
  })
})

describe('подпись отделения на карте', () => {
  it('берёт номер, различая ТОСП и головное отделение', () => {
    // ТОСП — не то же самое, что головное: на карте это разные точки, и
    // одинаковая подпись «МФЦ №9» у обеих сбивала бы с толку.
    expect(shortName('МФЦ №9 по городу Донецк')).toBe('МФЦ №9')
    expect(shortName('ТОСП г. Донецк МФЦ №9 г. Донецк')).toBe('ТОСП №9')
  })

  it('без номера берёт населённый пункт из адреса', () => {
    expect(shortName('МФЦ по городу Волноваха', 'г. Волноваха, ул. Ленина, 88')).toBe('Волноваха')
    expect(shortName('ТОСП пгт. Северное МФЦ', 'пгт Северное, ул. Минская, 30а')).toBe('Северное')
  })

  it('не оставляет пустую подпись, когда взять нечего', () => {
    expect(shortName('Пункт выдачи', null).length).toBeGreaterThan(0)
  })
})

describe('экранирование', () => {
  it('обезвреживает разметку в имени отделения', () => {
    // Разметка карты собирается строкой ради скорости, а имена вводит человек.
    expect(esc('<script>alert("1")</script>')).toBe('&lt;script&gt;alert(&quot;1&quot;)&lt;/script&gt;')
    expect(esc('МФЦ «Восток» & Ко')).toBe('МФЦ «Восток» &amp; Ко')
  })
})
