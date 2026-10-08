/**
 * Читаемый текст поверх заливки (08.10.2026).
 *
 * Числа в клетках тепловой карты стояли тёмным цветом на любой клетке, и на
 * насыщенной клетке матрицы рисков «1» почти пропадала. Белый текст на
 * насыщенном не выход: в тёмной теме шкала идёт от тёмного к СВЕТЛОМУ, и белое
 * на светлой клетке пропадало бы так же. Поэтому цвет выбирается по яркости
 * самой клетки — той, что получится из шкалы для этого значения.
 */

type RGB = [number, number, number]

function parseHex(hex: string): RGB | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const h = m[1].length === 3 ? m[1].split('').map((c) => c + c).join('') : m[1]
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB
}

/** Относительная яркость по WCAG (0 — чёрный, 1 — белый). */
function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** Цвет шкалы в точке t ∈ [0, 1] — так же, как его интерполирует ECharts. */
export function colorAt(palette: string[], t: number): string | null {
  const cs = palette.map(parseHex)
  if (!cs.length || cs.some((c) => !c)) return null
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (cs.length - 1)
  const i = Math.min(cs.length - 2, Math.floor(x))
  if (cs.length === 1) return palette[0]
  const f = x - i
  const a = cs[i] as RGB
  const b = cs[i + 1] as RGB
  const mix = a.map((v, k) => Math.round(v + (b[k] - v) * f))
  return '#' + mix.map((v) => v.toString(16).padStart(2, '0')).join('')
}

const DARK = '#1f1a17'
const LIGHT = '#ffffff'

/** Тёмный или белый текст — какой контрастнее на этой заливке. */
export function textOn(bg: string | null): string {
  const c = bg ? parseHex(bg) : null
  if (!c) return DARK
  const l = luminance(c)
  // Контраст с белым (1.05 / (l + 0.05)) против контраста с тёмным.
  const dark = luminance(parseHex(DARK) as RGB)
  return 1.05 / (l + 0.05) >= (l + 0.05) / (dark + 0.05) ? LIGHT : DARK
}
