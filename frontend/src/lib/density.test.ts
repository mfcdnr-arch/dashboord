// Плотность страницы дашборда. Числа легко «поправить на глаз» следующей
// правкой, а заметить это можно только открыв дашборд на нужном экране —
// поэтому правила закреплены тестом.
import { describe, expect, it } from 'vitest'
import { DENSITY, DENSITY_KEY, loadDensity, saveDensity } from './density'
import { GAP, ROW_H, flowItems } from './flowLayout'

const widgets = [
  { id: 'a', widget_type: 'kpi' },
  { id: 'b', widget_type: 'bar' },
  { id: 'c', widget_type: 'table' },
]

describe('плотность', () => {
  it('«просторно» повторяет прежние числа страницы — у того, кто не трогал переключатель, вид не меняется', () => {
    expect(DENSITY.comfortable.rowH).toBe(ROW_H)
    expect(DENSITY.comfortable.gap).toBe(GAP)
  })

  it('«компактно» действительно компактнее по КАЖДОЙ мере', () => {
    const c = DENSITY.compact, w = DENSITY.comfortable
    expect(c.rowH).toBeLessThan(w.rowH)
    expect(c.gap).toBeLessThan(w.gap)
    expect(c.pad).toBeLessThan(w.pad)
    expect(c.title).toBeLessThanOrEqual(w.title)
    // Нижняя граница: при ряде мельче 30px у карточки показателя появляется
    // внутренняя прокрутка — цифра, ради которой она стоит, уезжает под край.
    expect(c.rowH).toBeGreaterThanOrEqual(30)
  })

  it('уплотнение меняет высоту, но НЕ перекладывает страницу', () => {
    const wide = flowItems(widgets, 1400)
    const dense = flowItems(widgets, 1400, undefined, DENSITY.compact)
    expect(dense.map((i) => i.span)).toEqual(wide.map((i) => i.span))
    expect(dense.map((i) => i.id)).toEqual(wide.map((i) => i.id))
    dense.forEach((d, i) => { expect(d.height).toBeLessThan(wide[i].height) })
  })

  it('выбор запоминается у человека и по умолчанию просторный', () => {
    localStorage.removeItem(DENSITY_KEY)
    expect(loadDensity()).toBe('comfortable')
    saveDensity('compact')
    expect(loadDensity()).toBe('compact')
    saveDensity('comfortable')
    expect(loadDensity()).toBe('comfortable')
    localStorage.setItem(DENSITY_KEY, 'что-то чужое')
    expect(loadDensity()).toBe('comfortable')
    localStorage.removeItem(DENSITY_KEY)
  })
})
