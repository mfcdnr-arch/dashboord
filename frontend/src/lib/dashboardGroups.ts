import type { Dashboard } from '../api'

/**
 * Разложить отчёты по объектам: «все отчёты отдела ИТ вместе, потом другого».
 *
 * Вперемешку список не читается: строки одинаковы на вид, и человек не понимает,
 * к какому подразделению относится отчёт. Внутри объекта — свежие сверху: чаще
 * всего нужен последний, а не тот, что завели первым.
 *
 * Отчёты без объекта собираются в конце отдельной группой: прятать их нельзя
 * (они существуют), но и мешать их с чужими незачем.
 */
export const NO_OBJECT = 'Без объекта'

export function groupByObject(items: Dashboard[]): [string, Dashboard[]][] {
  const map = new Map<string, Dashboard[]>()
  for (const d of items) {
    const key = d.object_name || NO_OBJECT
    map.set(key, [...(map.get(key) || []), d])
  }
  const when = (d: Dashboard) => new Date(d.updated_at || d.created_at || 0).getTime()
  for (const list of map.values()) list.sort((a, b) => when(b) - when(a))
  return [...map.entries()].sort((a, b) => {
    if (a[0] === NO_OBJECT) return 1
    if (b[0] === NO_OBJECT) return -1
    return a[0].localeCompare(b[0], 'ru')
  })
}

/**
 * Разложить отчёты по НАПРАВЛЕНИЯМ (этап 3, 29.09.2026) — в порядке, который
 * задал человек, «Без направления» в конце.
 *
 * Число в заголовке группы — с сервера (`count`): список грузится страницами
 * по 50, и счёт по загруженному врал бы, пока не нажато «Показать ещё».
 * Сервер считает только видимые этому человеку дашборды, так что число не
 * выдаёт чужих. При поиске или фильтре (`serverCounts=false`) число — сколько
 * НАЙДЕНО: «РЦО · отчётов: 3» над одной найденной строкой вводило бы в
 * заблуждение.
 */
export const NO_DIRECTION = 'Без направления'

export interface DirectionGroup { key: string; title: string; count: number; items: Dashboard[] }

export function groupByDirection(
  items: Dashboard[],
  directions: { id: string; name: string; dashboards: number }[],
  withoutCount = 0,
  serverCounts = true,
): DirectionGroup[] {
  const map = new Map<string, Dashboard[]>()
  for (const d of items) {
    const key = d.direction_id || ''
    map.set(key, [...(map.get(key) || []), d])
  }
  const when = (d: Dashboard) => new Date(d.updated_at || d.created_at || 0).getTime()
  for (const list of map.values()) list.sort((a, b) => when(b) - when(a))
  const out: DirectionGroup[] = []
  for (const dir of directions) {
    const list = map.get(dir.id)
    if (list?.length) {
      out.push({ key: dir.id, title: dir.name, items: list,
        count: serverCounts ? Math.max(dir.dashboards, list.length) : list.length })
    }
  }
  // Направление, которого нет в списке (заведено после загрузки списка), — не
  // терять его дашборды: показать под именем из самой строки.
  for (const [key, list] of map) {
    if (key && !directions.some((d) => d.id === key)) {
      out.push({ key, title: list[0].direction_name || NO_DIRECTION, count: list.length, items: list })
    }
  }
  const none = map.get('')
  if (none?.length) {
    out.push({ key: '', title: NO_DIRECTION, items: none,
      count: serverCounts ? Math.max(withoutCount, none.length) : none.length })
  }
  return out
}

/**
 * Фильтр списка по направлению, который ещё можно показать; иначе — «все».
 *
 * 🔴 Фильтр живёт отдельно от списка направлений, и они расходятся: удалили
 * направление, выбранное в фильтре, — список дашбордов пуст, а выпадающий
 * список показывает «все направления» (выбранного значения среди вариантов
 * нет); сняли направление у последних дашбордов при «без направления» —
 * вариант исчез; удалили все направления — пропал сам выпадающий список, и
 * пустой отфильтрованный список нечем сбросить. Проверяем при каждом
 * перечитывании направлений.
 */
export function keepDirFilter(
  filter: string,
  directions: { items: { id: string }[]; without: number } | null,
): string {
  if (!filter) return filter
  if (!directions || !directions.items.length) return ''
  if (filter === 'none') return directions.without > 0 ? filter : ''
  return directions.items.some((d) => d.id === filter) ? filter : ''
}
