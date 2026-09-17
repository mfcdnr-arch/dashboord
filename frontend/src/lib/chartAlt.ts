// Склонение берём общее (lib/text): вторая копия правила однажды разойдётся
// с первой, а разойдётся она молча — в тексте для диктора.
import { plural } from './text'

/**
 * Текстовая альтернатива графику — то, что услышит человек с диктором экрана.
 *
 * График рисуется в SVG и для программы чтения с экрана пуст: она сообщает
 * «изображение» и молчит о содержимом (в отчёте аудита — 0 из 26 типов).
 * Описание строится ИЗ САМОЙ опции графика, а не передаётся из места вызова:
 * так новый тип виджета получает его сам, и про это не придётся вспоминать —
 * тот же приём, что у подстановки цветов темы и выноса подсказки.
 *
 * У ECharts есть встроенный `aria.enabled`, но он сочиняет машинный текст
 * («серия 1 содержит 62 элемента») и на английском. Здесь — короткая сводка
 * на русском: что за график, сколько в нём категорий, где наибольшее и
 * наименьшее, каков итог. Полные данные человек берёт выгрузкой в Excel.
 */
import { fmtNumber } from './format'

const KIND: Record<string, string> = {
  bar: 'Столбчатая диаграмма',
  line: 'Линейный график',
  pie: 'Круговая диаграмма',
  gauge: 'Шкала',
  heatmap: 'Тепловая карта',
  scatter: 'Точечная диаграмма',
}

type Any = Record<string, any>

function asArray(v: unknown): Any[] {
  return Array.isArray(v) ? (v as Any[]) : v ? [v as Any] : []
}

/** Числовое значение точки: 12, [x, 12], {value: 12} или {value: [x, 12]}. */
function pointValue(p: unknown): number | null {
  if (typeof p === 'number') return Number.isFinite(p) ? p : null
  if (Array.isArray(p)) return pointValue(p[p.length - 1])
  if (p && typeof p === 'object' && 'value' in (p as Any)) return pointValue((p as Any).value)
  return null
}

function pointName(p: unknown): string | null {
  if (p && typeof p === 'object' && !Array.isArray(p) && 'name' in (p as Any)) {
    const n = (p as Any).name
    return typeof n === 'string' && n.trim() ? n.trim() : null
  }
  return null
}

export function describeChart(option: unknown): string {
  const opt = (option || {}) as Any
  const series = asArray(opt.series).filter(Boolean)
  if (!series.length) return 'График без данных'

  const type = String(series[0]?.type || '')
  const kind = KIND[type] || 'График'

  // Подписи категорий: ось с массивом `data` (у горизонтальных столбиков это
  // ось Y, поэтому смотрим обе), иначе — имена самих точек (круговая).
  const axes = [...asArray(opt.xAxis), ...asArray(opt.yAxis)]
  const catAxis = axes.find((a) => Array.isArray(a?.data) && a.data.length)
  const labels: string[] = (catAxis?.data || []).map((d: unknown) =>
    typeof d === 'string' ? d : (pointName(d) ?? String((d as Any)?.value ?? d ?? '')))

  const parts: string[] = []
  // Имена в госформах длинные («Отделение № 3 ГБУ "МФЦ ДНР" г. Мариуполь
  // ул.Нахимова, 172»), а описание читают вслух — поэтому режем: сводка должна
  // звучать секунды, за подробностями есть выгрузка в Excel.
  const short = (t: string, limit = 44) => (t.length > limit ? t.slice(0, limit - 1).trimEnd() + '…' : t)
  // Имена рядов режем короче имён категорий: их называют, чтобы человек понял,
  // О ЧЁМ ряд, а полный текст легенды он и так видит глазами.
  const seriesName = (t: string) => short(t, 30)
  const named = series.map((x) => (typeof x?.name === 'string' ? x.name.trim() : '')).filter(Boolean)

  const points = asArray(series[0]?.data)
  const vals: { name: string; v: number }[] = []
  points.forEach((p, i) => {
    const v = pointValue(p)
    if (v === null) return
    vals.push({ name: pointName(p) ?? labels[i] ?? `${i + 1}`, v })
  })

  if (type === 'gauge') {
    const max = series[0]?.max
    const v = vals.length ? fmtNumber(vals[0].v) : '—'
    return `${kind}${named[0] ? `: ${short(named[0])}` : ''}. Значение ${v}${typeof max === 'number' ? ` из ${fmtNumber(max)}` : ''}.`
  }

  if (!vals.length) return `${kind}${named[0] ? `: ${short(named[0])}` : ''}. Данных нет.`

  // Первая фраза отвечает «что это и какого размера». Ряды называем не больше
  // двух: тринадцать имён подряд — это уже чтение легенды вслух.
  if (series.length > 1) {
    const list = named.slice(0, 2).map(seriesName).join(', ')
    parts.push(`${kind}, ${series.length} ${plural(series.length, 'ряд', 'ряда', 'рядов')}`
      + (list ? ` (${list}${named.length > 2 ? ' и другие' : ''})` : '')
      + `, ${vals.length} ${plural(vals.length, 'категория', 'категории', 'категорий')}`)
  } else {
    parts.push(`${kind}${named[0] ? `: ${seriesName(named[0])}` : ''}, ${vals.length} `
      + plural(vals.length, 'значение', 'значения', 'значений'))
  }

  // Дальше — только ПЕРВЫЙ ряд: он основной показатель виджета. При нескольких
  // рядах это сказано прямо, иначе числа читались бы как общие.
  const about = series.length > 1 && named[0] ? `По ряду «${seriesName(named[0])}»: ` : ''
  const max = vals.reduce((a, b) => (b.v > a.v ? b : a))
  const min = vals.reduce((a, b) => (b.v < a.v ? b : a))
  if (max.name !== min.name) {
    parts.push(`${about}наибольшее — ${short(max.name)}: ${fmtNumber(max.v)}`)
    parts.push(`наименьшее — ${short(min.name)}: ${fmtNumber(min.v)}`)
  }

  // У линии важнее направление, чем экстремумы: с чего начали и чем кончили.
  if (type === 'line' && vals.length > 1) {
    const first = vals[0], last = vals[vals.length - 1]
    const d = last.v - first.v
    const way = d > 0 ? 'рост' : d < 0 ? 'снижение' : 'без изменений'
    parts.push(`от ${short(first.name)}: ${fmtNumber(first.v)} до ${short(last.name)}: ${fmtNumber(last.v)} — ${way}`)
  } else if (type === 'bar' || type === 'pie') {
    parts.push(`всего ${fmtNumber(vals.reduce((sum, x) => sum + x.v, 0))}`)
  }

  return parts.map((t, i) => (i === 0 ? t : t.charAt(0).toUpperCase() + t.slice(1))).join('. ') + '.'
}
