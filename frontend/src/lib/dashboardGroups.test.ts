// Группировка отчётов по объектам: «все отчёты отдела вместе».
//
// Правило легко потерять при следующей правке списка, а заметить потерю можно
// только глазами и только когда объектов станет больше одного.
import { describe, expect, it } from 'vitest'
import { groupByObject, NO_OBJECT } from './dashboardGroups'

const d = (id: string, object_name: string | null, updated_at: string) =>
  ({ id, name: id, object_name, updated_at, created_at: updated_at } as never)

describe('groupByObject', () => {
  it('собирает отчёты одного объекта вместе и сортирует объекты по алфавиту', () => {
    const g = groupByObject([
      d('a', 'МФЦ', '2026-08-01'), d('b', 'ИТ', '2026-08-02'), d('c', 'МФЦ', '2026-08-03'),
    ])
    expect(g.map(([name]) => name)).toEqual(['ИТ', 'МФЦ'])
    expect(g[1][1].map((x) => x.id)).toEqual(['c', 'a'])
  })

  it('внутри объекта свежие сверху — чаще всего нужен последний', () => {
    const [, list] = groupByObject([
      d('старый', 'ИТ', '2026-01-01'), d('свежий', 'ИТ', '2026-08-18'),
    ])[0]
    expect(list.map((x) => x.id)).toEqual(['свежий', 'старый'])
  })

  it('отчёты без объекта не мешаются с чужими и уходят в конец', () => {
    const g = groupByObject([d('ничей', null, '2026-08-18'), d('свой', 'ИТ', '2026-08-01')])
    expect(g.map(([name]) => name)).toEqual(['ИТ', NO_OBJECT])
  })
})
