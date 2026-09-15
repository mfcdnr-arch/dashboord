/**
 * Виртуализация широкой таблицы: считаем, что реально видно.
 *
 * Зачем. У ежедневного отчёта РЦО 63 строки × 327 граф — это 21 648 ячеек в
 * одном узле DOM (замерено на живом дашборде: 23 040 узлов страницы, из них
 * 94 % — таблица). Отрисовка занимает секунды, а ЛЮБОЕ взаимодействие
 * (сортировка кликом по заголовку, ввод в поиск) заставляет React пересобрать
 * их заново: замер сортировки не уложился в 45 секунд и был прерван по
 * таймауту — то есть на это время вкладка перестаёт отвечать.
 *
 * 🔴 Обрезка здесь неверна по существу: таблица — единственное место, где
 * человек законно хочет увидеть форму целиком, и «показаны первые 20 граф из
 * 327» превратило бы её в бесполезный огрызок. Поэтому рисуем только то, что
 * попало в окно прокрутки, а данные остаются все.
 */
import { describe, it, expect } from 'vitest'
import { visibleRange } from './virtual'

describe('visibleRange', () => {
  it('в начале списка показывает окно от нуля и не уходит в минус', () => {
    const r = visibleRange({ scroll: 0, viewport: 300, itemSize: 30, count: 100, overscan: 2 })
    expect(r.start).toBe(0)
    expect(r.padBefore).toBe(0)
    expect(r.end).toBeGreaterThanOrEqual(10)   // 300 / 30 = 10 видимых
  })

  it('прокрутка сдвигает окно, а распорка держит полосу прокрутки на месте', () => {
    const r = visibleRange({ scroll: 600, viewport: 300, itemSize: 30, count: 100, overscan: 2 })
    // 600 / 30 = 20-й элемент вверху, минус overscan
    expect(r.start).toBe(18)
    expect(r.padBefore).toBe(18 * 30)
    // Полная высота обязана сохраниться: иначе полоса прокрутки прыгает под
    // пальцем и до конца таблицы не добраться.
    const total = r.padBefore + (r.end - r.start) * 30 + r.padAfter
    expect(total).toBe(100 * 30)
  })

  it('в конце списка окно упирается в последний элемент', () => {
    const r = visibleRange({ scroll: 100 * 30, viewport: 300, itemSize: 30, count: 100, overscan: 2 })
    expect(r.end).toBe(100)
    expect(r.padAfter).toBe(0)
  })

  it('короткий список показывается целиком без распорок', () => {
    const r = visibleRange({ scroll: 0, viewport: 300, itemSize: 30, count: 5, overscan: 2 })
    expect(r.start).toBe(0)
    expect(r.end).toBe(5)
    expect(r.padBefore).toBe(0)
    expect(r.padAfter).toBe(0)
  })

  it('🔴 запас по краям нужен, чтобы при прокрутке не мелькала пустота', () => {
    const noOverscan = visibleRange({ scroll: 600, viewport: 300, itemSize: 30, count: 100, overscan: 0 })
    const withOverscan = visibleRange({ scroll: 600, viewport: 300, itemSize: 30, count: 100, overscan: 3 })
    expect(withOverscan.start).toBeLessThan(noOverscan.start)
    expect(withOverscan.end).toBeGreaterThan(noOverscan.end)
  })

  it('нулевой размер окна не роняет расчёт', () => {
    // Первый кадр до замера контейнера: viewport ещё 0. Отдать пустой диапазон
    // нельзя — таблица моргнёт пустотой; отдаём минимальное окно.
    const r = visibleRange({ scroll: 0, viewport: 0, itemSize: 30, count: 100, overscan: 2 })
    expect(r.end).toBeGreaterThan(r.start)
  })

  it('пустая таблица не даёт отрицательных распорок', () => {
    const r = visibleRange({ scroll: 0, viewport: 300, itemSize: 30, count: 0, overscan: 2 })
    expect(r.start).toBe(0)
    expect(r.end).toBe(0)
    expect(r.padBefore).toBe(0)
    expect(r.padAfter).toBe(0)
  })
})
