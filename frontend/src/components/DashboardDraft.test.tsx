import { describe, expect, it } from 'vitest'
import { aggregate, parseNum } from './DashboardDraft'

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
