import { describe, expect, it } from 'vitest'
import { aggregate, labelsAreUseful, logScaleAdvice, parseNum } from './DashboardDraft'
import { elideMiddle } from '../lib/text'

describe('elideMiddle', () => {
  it('сохраняет хвост — в нём различие показателей', () => {
    const a = 'Количество обращений за результатом оказания услуг в МФЦ · Факт · нарастающим итогом'
    const b = 'Количество обращений за результатом оказания услуг в МФЦ · Факт · за отчётную неделю'
    const [ea, eb] = [elideMiddle(a, 50), elideMiddle(b, 50)]
    expect(ea).not.toBe(eb)
    expect(ea.endsWith('нарастающим итогом')).toBe(true)
    expect(eb.endsWith('за отчётную неделю')).toBe(true)
    expect(ea.length).toBeLessThanOrEqual(50)
  })

  it('короткие имена не трогает', () => {
    expect(elideMiddle('Доля обращений, %', 50)).toBe('Доля обращений, %')
  })
})

describe('logScaleAdvice', () => {
  it('советует логарифм, когда маленький столбик иначе не виден', () => {
    // 110 000 записавшихся против 183 подключённых МФЦ — случай заказчика.
    const { helps, spread } = logScaleAdvice([109993, 183, 67])
    expect(helps).toBe(true)
    expect(Math.round(spread)).toBe(1642)
  })

  it('на сравнимых значениях оставляет обычную шкалу', () => {
    expect(logScaleAdvice([100, 120, 90]).helps).toBe(false)
  })

  it('ноль и отрицательные значения на логарифм не пускает — их там нет', () => {
    expect(logScaleAdvice([0, 100000]).helps).toBe(false)
    expect(logScaleAdvice([-5, 100000]).helps).toBe(false)
  })
})

describe('labelsAreUseful', () => {
  it('названия районов годятся в подписи графика', () => {
    expect(labelsAreUseful([['Донецк', '1'], ['Макеевка', '2']], 0)).toBe(true)
  })

  it('«№ п/п» не годится — график выродится в безымянные столбики', () => {
    expect(labelsAreUseful([['1', '10'], ['2', '20']], 0)).toBe(false)
  })

  it('одна строка или одинаковые подписи — тоже не годятся', () => {
    expect(labelsAreUseful([['Донецк', '1']], 0)).toBe(false)
    expect(labelsAreUseful([['Итого', '1'], ['Итого', '2']], 0)).toBe(false)
  })
})

describe('parseNum', () => {
  it('читает числа так же, как бэкенд', () => {
    expect(parseNum('7078')).toBe(7078)
    expect(parseNum('12 040')).toBe(12040)   // разрядный пробел
    expect(parseNum('12 040')).toBe(12040)  // неразрывный пробел
    expect(parseNum('12,4')).toBe(12.4)      // десятичная запятая
    expect(parseNum('18,9%')).toBe(18.9)
    expect(parseNum('И.И. Иванов')).toBeNull()
    expect(parseNum('')).toBeNull()
  })
})

describe('aggregate', () => {
  it('складывает количества', () => {
    expect(aggregate('Количество МФЦ', [16, 11, 7])).toEqual({ value: 34, kind: 'сумма' })
  })

  it('усредняет доли и проценты — суммировать их бессмысленно', () => {
    // Дефект, найденный при живой проверке: карточка «Доля обращений, %»
    // показывала сумму процентов, то есть заведомо неверную цифру.
    expect(aggregate('Доля обращений, %', [10, 20])).toEqual({ value: 15, kind: 'среднее' })
    expect(aggregate('Удельный вес', [1, 3]).kind).toBe('среднее')
  })

  it('не падает на пустом наборе', () => {
    expect(aggregate('Что угодно', []).value).toBe(0)
  })
})
