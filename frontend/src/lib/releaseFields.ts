import type { FieldMap } from '../api'

export type PreviewColumn = {
  column_index: number
  field_code: string
  field_name: string
  data_type: string
}

/**
 * Показатели выпуска по текущей разметке.
 *
 * Ключевое правило — про КОДЫ. Показатель связывается между неделями кодом
 * поля, а не названием: виджеты и формулы ссылаются именно на код. Код,
 * вычисленный по заголовку файла, устойчив только пока человек ничего не
 * переименовывал; стоит ему дать графе своё имя — и в следующем файле код,
 * выведенный из заголовка, уже не совпадёт с тем, под которым лежат прошлые
 * недели. Показатель на дашборде тихо распался бы на два.
 *
 * Поэтому при подставленной разметке прошлого выпуска коды берутся ИЗ НЕЁ, а
 * из файла — только состав столбцов. Имена и типы человек правит поверх.
 */
export function buildReleaseFields(
  columns: PreviewColumn[],
  opts: {
    excluded: Set<number>
    labelColumn: number | null
    templateCodes?: Record<number, string>
    names?: Record<number, string>
    types?: Record<number, string>
  },
): FieldMap[] {
  const { excluded, labelColumn, templateCodes = {}, names = {}, types = {} } = opts
  const kept = columns.filter((c) => !excluded.has(c.column_index))
  if (!kept.length || labelColumn === null) return []
  return kept.map((c) => ({
    column_index: c.column_index,
    field_code: templateCodes[c.column_index] ?? c.field_code,
    field_name: (names[c.column_index] ?? c.field_name).trim() || c.field_name,
    data_type: types[c.column_index] ?? c.data_type,
    is_row_label: c.column_index === labelColumn,
  }))
}
