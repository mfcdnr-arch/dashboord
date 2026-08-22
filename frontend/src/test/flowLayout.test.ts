import { describe, expect, it } from 'vitest'
import { FLOW_SIZE, flowItems } from '../lib/flowLayout'

const w = (id: string, t: string) => ({ id, widget_type: t })

describe('flowItems', () => {
  it('на обычном экране карточки идут по три в ряд, таблица — во всю ширину', () => {
    const items = flowItems([w('a', 'kpi'), w('b', 'kpi'), w('c', 'table')], 900)
    expect(items[0].span).toBe(4)
    expect(items[1].span).toBe(4)
    expect(items[2].span).toBe(12)
  })

  it('на узком экране карточка расширяется, а не сжимается до нечитаемой', () => {
    // 600px: треть ряда — это 192px, имя госформы там не помещается
    const [item] = flowItems([w('a', 'kpi')], 600)
    expect(item.span).toBeGreaterThan(4)
    expect(12 % item.span).toBe(0)
  })

  it('на широком мониторе карточки уплотняются до четырёх в ряд', () => {
    const [item] = flowItems([w('a', 'kpi')], 1900)
    expect(item.span).toBe(3)
  })

  it('графики идут по два в ряд, таблицы — во всю ширину', () => {
    const items = flowItems([w('a', 'table'), w('b', 'compare'), w('c', 'pie'), w('d', 'bar')], 1500)
    expect(items.map((i) => i.span)).toEqual([12, 6, 6, 6])
  })

  it('графики не уплотняются дальше половины ряда — им нужна ширина', () => {
    const items = flowItems([w('a', 'bar'), w('b', 'compare')], 2400)
    expect(items.map((i) => i.span)).toEqual([6, 6])
  })

  it('ширина всегда делитель 12 — иначе ряд из «двух с половиной» карточек', () => {
    for (const width of [400, 600, 760, 900, 1200, 1500, 1900, 2400]) {
      for (const type of Object.keys(FLOW_SIZE)) {
        const [item] = flowItems([w('x', type)], width)
        expect(12 % item.span, `${type} @ ${width} → span ${item.span}`).toBe(0)
      }
    }
  })

  it('свёрнутый виджет занимает один ряд по высоте и не тянется по содержимому', () => {
    const [item] = flowItems([w('a', 'table')], 900, (id) => id === 'a')
    expect(item.height).toBe(40)
    expect(item.auto).toBe(false)
  })

  it('карточка показателя тянется по содержимому, график — нет', () => {
    const [kpi, bar] = flowItems([w('a', 'kpi'), w('b', 'bar')], 900)
    expect(kpi.auto).toBe(true)
    expect(bar.auto).toBe(false)
  })

  it('незнакомый тип получает половину ряда, а не падает', () => {
    const [item] = flowItems([w('a', 'sunburst')], 900)
    expect(item.span).toBe(6)
  })
})
