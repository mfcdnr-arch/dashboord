import { describe, expect, it } from 'vitest'
import { FIT_MIN_FREE, FIT_SLACK, fitChartHeight } from './fitHeight'

const MIN = 118

describe('fitChartHeight — высота графика под место в карточке', () => {
  it('пустоту под графиком забирает график, за один шаг', () => {
    // Замер 30.09 на «Сравнении»: карточка отдаёт 346px, график 226, подписи и
    // кнопки под ним ещё 26 — внизу оставалось 94px пустоты.
    const next = fitChartHeight({ room: 346, content: 252, chart: 226, cur: 226, min: MIN })
    expect(next).toBe(346 - 26 - FIT_SLACK)
  })

  it('переполнение ужимает график ровно настолько, чтобы всё поместилось', () => {
    // Второй исход того же замера: график 408 в месте 346, прокрутка на 104px.
    const next = fitChartHeight({ room: 346, content: 450, chart: 408, cur: 408, min: MIN })
    expect(next).toBe(346 - (450 - 408) - FIT_SLACK)
  })

  it('результат сходится: повторный расчёт по новой высоте ничего не меняет', () => {
    const other = 26
    const first = fitChartHeight({ room: 346, content: 226 + other, chart: 226, cur: 226, min: MIN })!
    expect(fitChartHeight({ room: 346, content: first + other, chart: first, cur: first, min: MIN })).toBeNull()
  })

  it('🔴 карточка с высотой по содержимому неподвижна — график не сползает и не растёт', () => {
    // В такой карточке место всегда равно содержимому (с точностью до отступа
    // последнего блока). «Ужать на запас» — и карточка ужмётся следом, шаг за
    // шагом до минимума; «вырасти на отступ» — и она будет расти бесконечно.
    expect(fitChartHeight({ room: 300, content: 300, chart: 196, cur: 196, min: MIN })).toBeNull()
    expect(fitChartHeight({ room: 306, content: 300, chart: 196, cur: 196, min: MIN })).toBeNull()
    expect(fitChartHeight({ room: 300, content: 301, chart: 196, cur: 196, min: MIN })).toBeNull()
  })

  it('небольшой зазор — это отступы, а не пустота', () => {
    expect(fitChartHeight({ room: 300, content: 300 - (FIT_MIN_FREE - 1), chart: 200, cur: 200, min: MIN })).toBeNull()
    expect(fitChartHeight({ room: 300, content: 300 - FIT_MIN_FREE, chart: 200, cur: 200, min: MIN })).not.toBeNull()
  })

  it('ниже минимума не ужимаем: пусть лучше будет прокрутка, чем нечитаемый график', () => {
    expect(fitChartHeight({ room: 150, content: 400, chart: 196, cur: 196, min: MIN })).toBe(MIN)
  })
})
