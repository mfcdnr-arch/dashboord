import { describe, expect, it } from 'vitest'
import { DEFAULT_SIZE, resizeOnTypeChange } from './shared'

/**
 * Смена ВИДА виджета должна менять и размер — но не затирать подогнанный руками.
 *
 * Жалоба заказчика 22.09.2026: «хотел поменять размер и вид виджета — не
 * получилось». Сама смена работала, но размер оставался прежним: карточка 3×3,
 * превращённая в таблицу, оставалась рамкой на три строки.
 */
describe('resizeOnTypeChange', () => {
  it('карточку, превращённую в таблицу, расширяет до размера таблицы', () => {
    const kpi = DEFAULT_SIZE.kpi
    expect(resizeOnTypeChange({ widget_type: 'kpi', width: kpi.w, height: kpi.h }, 'table'))
      .toEqual(DEFAULT_SIZE.table)
  })

  it('матрица получает свою ширину во весь ряд, а не остаётся карточкой', () => {
    const kpi = DEFAULT_SIZE.kpi
    expect(resizeOnTypeChange({ widget_type: 'kpi', width: kpi.w, height: kpi.h }, 'matrix'))
      .toEqual(DEFAULT_SIZE.matrix)
  })

  it('подогнанный РУКАМИ размер не трогает', () => {
    // Человек растянул карточку под свою страницу — это его решение, а не
    // умолчание типа, и перебивать его нельзя.
    expect(resizeOnTypeChange({ widget_type: 'kpi', width: 7, height: 9 }, 'table')).toBeNull()
  })

  it('тот же вид — ничего не меняет', () => {
    const t = DEFAULT_SIZE.table
    expect(resizeOnTypeChange({ widget_type: 'table', width: t.w, height: t.h }, 'table')).toBeNull()
  })

  it('виды с одинаковым умолчанием размер не дёргают', () => {
    // dynamics и yoy оба 6×6: лишняя запись размера только создала бы
    // впечатление, что виджет «прыгнул», хотя ничего не изменилось.
    expect(DEFAULT_SIZE.dynamics).toEqual(DEFAULT_SIZE.yoy)
    const d = DEFAULT_SIZE.dynamics
    expect(resizeOnTypeChange({ widget_type: 'dynamics', width: d.w, height: d.h }, 'yoy')).toBeNull()
  })

  it('неизвестный вид уходит в запасной размер, а не роняет расчёт', () => {
    expect(resizeOnTypeChange({ widget_type: 'kpi', width: 3, height: 3 }, 'ztest_unknown'))
      .toEqual({ w: 4, h: 4 })
  })
})
