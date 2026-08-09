import { describe, expect, it } from 'vitest'
import { distinctLabels, elideMiddle } from './text'

describe('elideMiddle', () => {
  it('сохраняет хвост имени — им и различаются показатели госформ', () => {
    const long = 'Количество обращений за результатом оказания услуг в МФЦ · Факт · за отчётную неделю'
    const out = elideMiddle(long, 40)
    expect(out.length).toBeLessThanOrEqual(40)
    expect(out.endsWith('за отчётную неделю')).toBe(true)
    expect(out).toContain('…')
  })

  it('короткое имя не трогает', () => {
    expect(elideMiddle('Обращения', 40)).toBe('Обращения')
  })
})

describe('distinctLabels', () => {
  const forms = [
    'Количество обращений за результатом оказания услуг в МФЦ · Факт · нарастающим итогом',
    'Количество отправленных уведомлений о готовности результатов · Факт · нарастающим итогом',
    'Количество пользователей, записавшихся на посещение МФЦ · Факт · нарастающим итогом',
  ]

  it('оставляет только различающую часть имени', () => {
    const out = distinctLabels(forms)
    expect(out[0]).toBe('обращений за результатом оказания услуг в МФЦ')
    expect(out[1]).toContain('отправленных уведомлений')
    expect(new Set(out).size).toBe(3) // подписи различимы
  })

  it('не трогает имена без общей части', () => {
    const names = ['Принято', 'Выдано']
    expect(distinctLabels(names)).toEqual(names)
  })

  it('возвращает исходные имена, если различающая часть пуста', () => {
    // одинаковые имена: отрезать нечего, иначе получились бы пустые подписи
    const same = ['Количество обращений', 'Количество обращений']
    expect(distinctLabels(same)).toEqual(same)
  })

  it('одно имя возвращает как есть', () => {
    expect(distinctLabels(['Количество обращений'])).toEqual(['Количество обращений'])
  })
})
