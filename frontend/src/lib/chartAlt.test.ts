import { describe, it, expect } from 'vitest'
import { describeChart } from './chartAlt'

/** Сравниваем без учёта регистра: тест держит СМЫСЛ сводки, а не её огласовку —
 *  иначе он ломался бы от каждой правки формулировки. */
const has = (t: string, s: string) => expect(t.toLowerCase()).toContain(s.toLowerCase())

describe('текстовая альтернатива графику', () => {
  it('называет вид, число значений, крайние точки и итог', () => {
    const t = describeChart({
      xAxis: { data: ['Донецк', 'Макеевка', 'Горловка'] },
      series: [{ type: 'bar', name: 'Принято', data: [300, 100, 200] }],
    })
    has(t, 'столбчатая диаграмма'); has(t, 'принято'); has(t, '3 значения')
    has(t, 'наибольшее — Донецк: 300'); has(t, 'наименьшее — Макеевка: 100'); has(t, 'всего 600')
  })

  it('у линии сообщает направление, а не только крайние значения', () => {
    const t = describeChart({ xAxis: { data: ['июль', 'август'] }, series: [{ type: 'line', data: [100, 140] }] })
    has(t, 'линейный график'); has(t, 'рост')
    // сумма точек ряда смысла не имеет — итога у линии быть не должно
    expect(t.toLowerCase()).not.toContain('всего')
  })

  it('берёт подписи у горизонтальных столбиков (категории на оси Y)', () => {
    const t = describeChart({ yAxis: { data: ['Первый', 'Второй'] }, xAxis: { type: 'value' }, series: [{ type: 'bar', data: [5, 9] }] })
    has(t, 'наибольшее — Второй')
  })

  it('понимает точки-объекты круговой диаграммы', () => {
    const t = describeChart({ series: [{ type: 'pie', data: [{ name: 'ЕСИА', value: 70 }, { name: 'Прочие', value: 30 }] }] })
    has(t, 'круговая диаграмма'); has(t, 'наибольшее — ЕСИА: 70')
  })

  it('у шкалы сообщает значение и предел, а не «наибольшее»', () => {
    const t = describeChart({ series: [{ type: 'gauge', max: 750, data: [{ value: 656 }] }] })
    has(t, 'шкала'); has(t, '656'); has(t, 'из 750')
    expect(t.toLowerCase()).not.toContain('наибольшее')
  })

  it('при нескольких рядах называет их число и говорит, о каком ряде числа', () => {
    const t = describeChart({
      xAxis: { data: ['А', 'Б'] },
      series: [{ type: 'bar', name: 'План', data: [1, 2] }, { type: 'bar', name: 'Факт', data: [3, 4] }],
    })
    has(t, '2 ряда'); has(t, 'план'); has(t, 'категории')
    // без этой оговорки числа первого ряда читаются как общие по графику
    has(t, 'по ряду «План»')
  })

  it('длинные имена укорачиваются, а сводка остаётся короткой', () => {
    const long = 'Отделение № 3 ГБУ "МФЦ ДНР" г. Мариуполь ул. Нахимова, 172'
    const t = describeChart({
      xAxis: { data: [long, 'Б'] },
      series: Array.from({ length: 13 }, (_, i) => ({ type: 'bar', name: `Очень длинное имя показателя номер ${i}`, data: [10, 1] })),
    })
    expect(t).not.toContain(long)          // целиком такое имя вслух не читают
    expect(t.length).toBeLessThan(260)     // сводка — секунды, а не полминуты
    has(t, '13 рядов')
  })

  it('пустой график и пропуски не роняют описание', () => {
    expect(describeChart({})).toBe('График без данных')
    has(describeChart({ series: [{ type: 'bar', data: [] }] }), 'данных нет')
    has(describeChart({ xAxis: { data: ['А', 'Б'] }, series: [{ type: 'bar', data: [null, 7] }] }), '1 значение')
  })
})
