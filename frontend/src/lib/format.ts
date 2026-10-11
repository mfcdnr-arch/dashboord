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
 * Дробное число с ФИКСИРОВАННЫМ числом знаков, по-русски.
 *
 * `toFixed` всегда ставит точку, и на одном экране соседствовали две записи
 * одного числа: целые шли как «929 825», а проценты как «3.50». Тот же
 * дефект уже чинили в дашбордах (09.08) и в «Статистике услуг» (11.09) —
 * здесь общий помощник, чтобы не чинить его в третий раз поштучно.
 */
/** Процент по-русски: «63,8 %». Одна запись на систему — иначе на экране
 *  соседствуют «583 636» по-русски и «63.8%» с точкой (так было в разделе
 *  «Статистика услуг» до 11.09.2026). */
export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null) return '—'
  return `${n.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`
}

export function fmtFixed(n: number | null | undefined, digits = 2): string {
  if (n == null || !isFinite(n)) return '—'
  return n.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
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

/** Значение ячейки таблицы для экрана.
 *
 *  Даты в формах-реестрах («Дата/время/место», «Срок решения») приходят
 *  строкой ISO — «2026-10-06» — и в таблице читались машинно, да ещё рвались
 *  переносом по дефису. Выгрузка в Excel переводила их в дату и раньше; экран
 *  теперь печатает так же, как всё остальное в системе: 06.10.2026. Сортировка
 *  идёт по исходному значению — ISO сортируется верно.
 */
/** Единица графы-длительности: сервер хранит «ч:мм:сс» в минутах (11.10.2026). */
export const DURATION_UNIT = 'мин'

/**
 * Длительность в минутах → «14 мин 22 с», «1 ч 27 мин», «45 с».
 *
 * Отчёт «Среднее время обслуживания / ожидания» пишет время как «00:14:22».
 * Хранить его приходится числом (иначе ни среднего, ни сравнения), а «14,37
 * мин» руководитель читать не станет: он ждёт минут и секунд. Секунды при
 * часе и больше не нужны — «1 ч 27 мин 16 с» шумнее, чем полезнее.
 */
export function fmtDuration(min: number | null | undefined): string {
  if (min == null || !isFinite(min)) return '—'
  const sign = min < 0 ? '−' : ''
  const total = Math.round(Math.abs(min) * 60)
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), sec = total % 60
  if (h) return `${sign}${h} ч${m ? ` ${m} мин` : ''}`
  if (m) return `${sign}${m} мин${sec ? ` ${sec} с` : ''}`
  return `${sign}${sec} с`
}

/** Число с единицей: длительность — минутами и секундами, остальное — «12 345 ед.». */
export function fmtWithUnit(v: number | null | undefined, unit?: string | null): string {
  if (unit === DURATION_UNIT) return fmtDuration(v)
  return fmtNumber(v) + (unit && v != null ? ` ${unit}` : '')
}

export function fmtCell(v: unknown, unit?: string | null): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'number') return unit === DURATION_UNIT ? fmtDuration(v) : fmtNumber(v)
  const s = String(v)
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T]00:00(?::00)?)?$/.exec(s.trim())
  return m ? `${m[3]}.${m[2]}.${m[1]}` : s
}

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

/** Ряд для мини-графика: пропуски выброшены ВМЕСТЕ со своими периодами.
 *
 *  Пропуск в форме — это «отчёта не было», а не «было ноль», поэтому рисовать
 *  его нулём нельзя. Но выбросить одно значение и оставить все даты значит
 *  сдвинуть подписи: подсказка при наведении назовёт чужую дату, причём
 *  правдоподобную — тем и опасно. Пары режем вместе.
 */
export function sparkSeries(
  values: (number | null | undefined)[],
  periods?: (string | null | undefined)[],
): { values: number[]; periods: (string | null)[] } {
  const out: { values: number[]; periods: (string | null)[] } = { values: [], periods: [] }
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) return
    out.values.push(v)
    out.periods.push(periods?.[i] ?? null)
  })
  return out
}
