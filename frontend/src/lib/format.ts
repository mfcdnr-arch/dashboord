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
