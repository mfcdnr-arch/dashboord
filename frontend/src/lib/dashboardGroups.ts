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
