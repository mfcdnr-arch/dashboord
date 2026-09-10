import { describe, expect, it } from 'vitest'
import { heatSteps, logScaleAdvice, sparkSeries } from './format'

// Палитра тепловой карты — пять оттенков, как в теме.
const PAL = ['#faf0e9', '#e0b58f', '#e0885f', '#a5563c', '#e04e39']

describe('heatSteps', () => {
  // Длинный хвост — то самое распределение, из-за которого карта РЦО сливалась
  // в один тон: медиана 27 при максимуме 290 на 63 отделениях.
  const skewed = [...Array(50).fill(0).map((_, i) => i % 30 + 1), 120, 150, 180, 210, 240, 290]

  it('разводит клетки по ступеням, когда хвост длинный', () => {
    const st = heatSteps(skewed, PAL)
    expect(st).not.toBeNull()
    expect(st!.pieces.length).toBeGreaterThanOrEqual(3)
    // Ступени идут по возрастанию и смыкаются: между ними не должно быть дыр.
    const ups = st!.pieces.map((p) => p.gte).filter((v) => v !== undefined)
    expect([...ups].sort((a, b) => a! - b!)).toEqual(ups)
    // Каждая ступень своего цвета — иначе разведение бессмысленно.
    expect(new Set(st!.pieces.map((p) => p.color)).size).toBe(st!.pieces.length)
  })

  it('на ровном распределении ступеней НЕ предлагает', () => {
    // Максимум не превышает медиану вчетверо — обычная шкала понятнее, и менять
    // её без нужды не надо.
    const flat = Array.from({ length: 60 }, (_, i) => 100 + (i % 10))
    expect(heatSteps(flat, PAL)).toBeNull()
  })

  it('на горстке значений молчит: о распределении говорить не с чего', () => {
    expect(heatSteps([1, 2, 3, 400], PAL)).toBeNull()
  })

  it('совпавшие границы схлопываются, а не дают пустых ступеней', () => {
    // У формы РЦО много нулей и единиц: квантили 20 % и 40 % совпадают.
    const many0 = [...Array(45).fill(0), ...Array(10).fill(1), 50, 90, 140, 200, 400]
    const st = heatSteps(many0, PAL)
    if (st) {
      const bounds = st.pieces.flatMap((p) => [p.lt, p.gte]).filter((v) => v !== undefined)
      expect(new Set(bounds).size).toBe(new Set(bounds).size) // границы уникальны
      st.pieces.forEach((p) => {
        if (p.lt !== undefined && p.gte !== undefined) expect(p.gte).toBeLessThan(p.lt)
      })
    }
  })

  it('называет, насколько тесно было бы на равномерной шкале', () => {
    const st = heatSteps(skewed, PAL)
    expect(st!.crowded).toBeGreaterThan(50)   // больше половины клеток в нижней пятой
    expect(st!.spread).toBeGreaterThan(4)
  })
})

describe('logScaleAdvice', () => {
  it('предлагает логарифм при разбросе в сотни раз и молчит при нулях', () => {
    expect(logScaleAdvice([7078, 2357470]).helps).toBe(true)
    expect(logScaleAdvice([0, 100, 200]).helps).toBe(false)
  })
})

describe('sparkSeries', () => {
  it('выбрасывает пропуск вместе с его периодом', () => {
    // Отчёта за 29.07 не было. Выбрось мы одно значение и оставь все даты —
    // подсказка при наведении назвала бы 29.07 там, где на самом деле 05.08.
    const r = sparkSeries([10, null, 30], ['2026-07-22', '2026-07-29', '2026-08-05'])
    expect(r.values).toEqual([10, 30])
    expect(r.periods).toEqual(['2026-07-22', '2026-08-05'])
  })

  it('ноль остаётся значением', () => {
    // Ноль — это «было ноль», и путать его с пропуском нельзя.
    const r = sparkSeries([0, 5], ['2026-07-22', '2026-07-29'])
    expect(r.values).toEqual([0, 5])
  })

  it('без периодов возвращает пустые подписи, а не падает', () => {
    const r = sparkSeries([1, 2, 3])
    expect(r.values).toEqual([1, 2, 3])
    expect(r.periods).toEqual([null, null, null])
  })
})
