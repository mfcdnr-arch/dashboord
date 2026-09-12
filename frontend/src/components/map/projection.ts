// Проекция и геометрия карты отделений.
//
// Равнопромежуточная проекция с поправкой на широту: республика — это
// 190×260 км, на таком размере искажения меньше толщины линии, а расчёт
// остаётся арифметикой. Полноценная картографическая проекция здесь дала бы
// ту же картинку ценой зависимости и лишнего кода.

/** Сжатие по долготе на широте региона. */
export const K = Math.cos((48.05 * Math.PI) / 180)
export const px = (lon: number): number => lon * K * 1000
export const py = (lat: number): number => -lat * 1000

export interface Rect { x: number; y: number; w: number; h: number }

export function ringPath(ring: number[][]): string {
  return 'M' + ring.map((p) => `${px(p[0]).toFixed(1)} ${py(p[1]).toFixed(1)}`).join('L') + 'Z'
}

export function boundsOf(ring: number[][], padRatio = 0.05): Rect {
  const xs = ring.map((p) => px(p[0]))
  const ys = ring.map((p) => py(p[1]))
  const x0 = Math.min(...xs), x1 = Math.max(...xs)
  const y0 = Math.min(...ys), y1 = Math.max(...ys)
  const pad = (x1 - x0) * padRatio
  return { x: x0 - pad, y: y0 - pad, w: (x1 - x0) + pad * 2, h: (y1 - y0) + pad * 2 }
}

/** Экранирование для SVG: имена отделений вводит человек, и они попадают в
 *  разметку, которую мы собираем строкой ради скорости отрисовки. */
export function esc(s: string): string {
  return String(s).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))
}

/** Короткая подпись отделения: на карте нужен номер, а не полное название на
 *  пол-экрана. Нет номера — берём населённый пункт из адреса. */
export function shortName(name: string, address?: string | null): string {
  const m = name.match(/№\s*(\d+)/)
  if (m) return (/^ТОСП/i.test(name) ? 'ТОСП №' : 'МФЦ №') + m[1]
  const c = (address || '').match(/^\s*(?:г\.|гор\.|пгт\.?|пос\.?|с\.)\s*([^,]+)/)
  return c ? c[1].trim() : name.slice(0, 18)
}

// Ширину подписи меряем ШРИФТОМ: у кириллицы буквы разной ширины, и оценка
// «число знаков × коэффициент» промахивается на треть — подпись садится на
// точку. Тот же приём уже используется для подписей осей на графиках.
let mc: CanvasRenderingContext2D | null = null
const wCache = new Map<string, number>()
export function textWidth(s: string, bold = false): number {
  const key = (bold ? 'b' : 'n') + s
  const hit = wCache.get(key)
  if (hit != null) return hit
  if (!mc) mc = document.createElement('canvas').getContext('2d')
  if (!mc) return s.length * 0.55
  mc.font = `${bold ? 'bold ' : ''}100px ${getComputedStyle(document.body).fontFamily}`
  const w = mc.measureText(s).width / 100
  wCache.set(key, w)
  return w
}
