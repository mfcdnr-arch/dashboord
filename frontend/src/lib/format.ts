// Единое форматирование чисел для интерфейса.
// Раньше одна и та же функция была скопирована в четыре компонента, и они
// разошлись: целые печатались по-русски («929 825»), а дробные через toFixed —
// с ТОЧКОЙ («37.18»). В одном окне соседствовали две записи одного числа.
export function fmtNumber(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return '—'
  return Number.isInteger(n)
    ? n.toLocaleString('ru-RU')
    : n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * Стоит ли рисовать график в логарифмической шкале.
 *
 * Когда показатели различаются на два порядка (2 357 470 против 7 078), на
 * линейной шкале маленькие столбики вырождаются в полоску у нуля — сравнить
 * их невозможно. Логарифм это исправляет, но у него нет ни нуля, ни
 * отрицательных значений, поэтому предлагаем его только для строго
 * положительных наборов.
 */
export function logScaleAdvice(values: number[]): { helps: boolean; spread: number } {
  const nums = values.filter((v) => typeof v === 'number' && isFinite(v))
  if (nums.length < 2 || nums.some((v) => !(v > 0))) return { helps: false, spread: 1 }
  const spread = Math.max(...nums) / Math.min(...nums)
  return { helps: spread >= 100, spread }
}

export interface HeatPiece { lt?: number; gte?: number; color: string }

/** Ступени цветовой шкалы тепловой карты — по квантилям значений.
 *
 *  Возвращает null, когда ступени не нужны: распределение ровное (максимум не
 *  превышает медиану вчетверо) или значений слишком мало, чтобы говорить о
 *  распределении вообще. Ровная шкала понятнее, и менять её без нужды не надо.
 *
 *  Границы, совпавшие между собой (у формы РЦО много нулей и единиц), схлопываются:
 *  две ступени с одинаковыми краями в легенде выглядели бы поломкой.
 */
export function heatSteps(values: number[], palette: string[]): null | { pieces: HeatPiece[]; spread: number; crowded: number } {
  const vals = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  if (vals.length < 20) return null
  const q = (p: number) => vals[Math.min(vals.length - 1, Math.floor(vals.length * p))]
  const max = vals[vals.length - 1]
  const median = q(0.5)
  if (!(max > 0) || max <= median * 4) return null
  const bounds = [...new Set([q(0.2), q(0.4), q(0.6), q(0.8)])].filter((b) => b > vals[0] && b < max)
  if (bounds.length < 2) return null
  // Насколько тесно было бы на равномерной шкале: доля клеток в нижней пятой.
  const crowded = Math.round(vals.filter((v) => v <= max * 0.2).length / vals.length * 100)
  const colors = palette.length >= bounds.length + 1
    ? palette.slice(0, bounds.length + 1)
    : Array.from({ length: bounds.length + 1 }, (_, i) => palette[Math.min(palette.length - 1, i)])
  const pieces: HeatPiece[] = [{ lt: bounds[0], color: colors[0] }]
  bounds.forEach((b, i) => {
    if (i + 1 < bounds.length) pieces.push({ gte: b, lt: bounds[i + 1], color: colors[i + 1] })
    else pieces.push({ gte: b, color: colors[i + 1] })
  })
  return { pieces, spread: max / Math.max(1, median), crowded }
}
