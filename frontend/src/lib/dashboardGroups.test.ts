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

import { groupByDirection, NO_DIRECTION } from './dashboardGroups'

const dd = (id: string, direction_id: string | null, updated_at: string, direction_name?: string) =>
  ({ id, name: id, direction_id, direction_name, updated_at, created_at: updated_at } as never)

describe('groupByDirection', () => {
  const dirs = [
    { id: 'r', name: 'РЦО', dashboards: 3 },
    { id: 'm', name: 'МАХ', dashboards: 1 },
  ]

  it('группы идут в порядке, заданном человеком, «Без направления» — в конце', () => {
    const g = groupByDirection([dd('a', null, '2026-09-01'), dd('b', 'm', '2026-09-01'),
      dd('c', 'r', '2026-09-01')], dirs, 1)
    expect(g.map((x) => x.title)).toEqual(['РЦО', 'МАХ', NO_DIRECTION])
  })

  it('число в заголовке — с сервера: страница загружена не вся', () => {
    const g = groupByDirection([dd('c', 'r', '2026-09-01')], dirs, 0)
    expect(g[0].count).toBe(3)
    expect(g[0].items).toHaveLength(1)
  })

  it('пустое направление группой не рисуется', () => {
    const g = groupByDirection([dd('c', 'r', '2026-09-01')], dirs, 0)
    expect(g.map((x) => x.title)).toEqual(['РЦО'])
  })

  it('дашборд направления, которого нет в списке, не теряется', () => {
    const g = groupByDirection([dd('x', 'new', '2026-09-01', 'Новое')], dirs, 0)
    expect(g).toEqual([expect.objectContaining({ title: 'Новое', count: 1 })])
  })

  it('внутри группы свежие сверху', () => {
    const g = groupByDirection([dd('old', 'r', '2026-08-01'), dd('new', 'r', '2026-09-01')], dirs, 0)
    expect(g[0].items.map((x) => x.id)).toEqual(['new', 'old'])
  })

  it('при поиске число — сколько найдено, а не сколько всего в направлении', () => {
    const g = groupByDirection([dd('c', 'r', '2026-09-01')], dirs, 0, false)
    expect(g[0].count).toBe(1)
  })
})

import { keepDirFilter } from './dashboardGroups'

describe('keepDirFilter', () => {
  const dirs = { items: [{ id: 'a' }, { id: 'b' }], without: 2 }
  it('действующее направление и «все» остаются как есть', () => {
    expect(keepDirFilter('a', dirs)).toBe('a')
    expect(keepDirFilter('', dirs)).toBe('')
    expect(keepDirFilter('none', dirs)).toBe('none')
  })
  it('удалённое направление сбрасывает фильтр — иначе пустой список под «все направления»', () => {
    expect(keepDirFilter('gone', dirs)).toBe('')
  })
  it('«без направления», когда таких не осталось, сбрасывается — вариант исчез из списка', () => {
    expect(keepDirFilter('none', { ...dirs, without: 0 })).toBe('')
  })
  it('нет ни одного направления — сбрасывается: выпадающего списка нет, сбросить нечем', () => {
    expect(keepDirFilter('a', { items: [], without: 3 })).toBe('')
    expect(keepDirFilter('none', null)).toBe('')
  })
})
