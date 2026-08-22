// «Когда это было» в плитках «Недавно смотрели». Правила легко сломать
// следующей правкой (склонение, граница «вчера»), а заметить это можно только
// глазами и только на нужных числах.
import { describe, expect, it } from 'vitest'
import { timeAgo } from './time'

const now = new Date(2026, 7, 22, 15, 0, 0) // 22.08.2026, 15:00
const at = (h: number, m = 0, day = 22) => new Date(2026, 7, day, h, m, 0).toISOString()

describe('timeAgo', () => {
  it('минуты и часы склоняются верно, включая ловушку 11–14', () => {
    expect(timeAgo(new Date(2026, 7, 22, 14, 59, 30).toISOString(), now)).toBe('только что')
    expect(timeAgo(at(14, 59), now)).toBe('1 минуту назад')
    expect(timeAgo(at(14, 21), now)).toBe('39 минут назад')
    expect(timeAgo(at(14, 39), now)).toBe('21 минуту назад')
    expect(timeAgo(at(14, 48), now)).toBe('12 минут назад')
    expect(timeAgo(at(13, 58), now)).toBe('1 час назад')
    expect(timeAgo(at(13), now)).toBe('2 часа назад')
    expect(timeAgo(at(4), now)).toBe('11 часов назад')
  })

  it('«вчера» считается по календарю, а не по 24 часам', () => {
    // 21.08 в 23:00 — это ВЧЕРА, хотя прошло всего 16 часов.
    expect(timeAgo(at(23, 0, 21), now)).toBe('вчера')
    expect(timeAgo(at(9, 0, 19), now)).toBe('3 дня назад')
  })

  it('дальше недели — обычная дата, а будущее не показываем «через N»', () => {
    expect(timeAgo(new Date(2026, 6, 30, 12).toISOString(), now)).toBe('30.07.2026')
    expect(timeAgo(at(15, 30), now)).toBe('только что')
    expect(timeAgo(null, now)).toBe('')
    expect(timeAgo('не дата', now)).toBe('')
  })
})
