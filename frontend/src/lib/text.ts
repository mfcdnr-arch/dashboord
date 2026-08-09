/**
 * Сокращает длинное имя, вырезая СЕРЕДИНУ.
 *
 * У составных заголовков госформ совпадает начало («Количество обращений за
 * результатом оказания услуг в МФЦ · Факт · …»), а различаются они хвостом
 * («нарастающим итогом» против «за отчётную неделю»). Обычная обрезка с конца
 * съедает единственное, что отличает показатели друг от друга, — на экране
 * получается несколько одинаковых на вид показателей.
 */
export function elideMiddle(text: string, max = 80): string {
  if (text.length <= max) return text
  const head = Math.max(10, Math.round((max - 1) * 0.3))
  const tail = max - 1 - head
  return `${text.slice(0, head).trimEnd()}…${text.slice(text.length - tail).trimStart()}`
}

/**
 * Убирает у набора имён ОБЩИЕ начало и конец, оставляя различающую часть.
 *
 * В госформах показатели называются по одному шаблону: «Количество … · Факт ·
 * нарастающим итогом**». На графике сравнения такие подписи выглядят одинаково,
 * а различие («обращений» / «отправленных уведомлений» / «записавшихся») сидит
 * в СЕРЕДИНЕ — то есть ровно там, где обычное сокращение его и вырезает.
 *
 * Общая часть отрезается по словам (не по буквам), иначе имя оборвётся на
 * половине слова. Если после отсечения что-то стало пустым, возвращаем исходные
 * имена: лучше длинно, чем непонятно.
 */
export function distinctLabels(names: string[]): string[] {
  if (names.length < 2) return names
  const words = names.map((n) => n.split(/\s+/).filter(Boolean))

  let prefix = 0
  while (words.every((w) => w.length > prefix + 1 && w[prefix] === words[0][prefix])) prefix++

  let suffix = 0
  while (words.every((w) => w.length > prefix + suffix + 1 && w[w.length - 1 - suffix] === words[0][words[0].length - 1 - suffix])) suffix++

  if (!prefix && !suffix) return names
  const cut = words.map((w) => w.slice(prefix, w.length - suffix).join(' ').trim())
  // Смысл отсечения — РАЗЛИЧИТЬ подписи. Если после него что-то опустело или
  // подписи всё равно неотличимы друг от друга, контекст терять незачем.
  if (cut.some((s) => !s)) return names
  const uniqCut = new Set(cut).size
  const uniqNames = new Set(names).size
  // Обрезаем, только если это даёт РАЗЛИЧИМЫЕ подписи и ничего не склеивает.
  // Одинаковые имена (uniqNames === 1) различить нельзя — оставляем как есть.
  if (uniqCut !== uniqNames || uniqNames < 2) return names
  return cut
}
