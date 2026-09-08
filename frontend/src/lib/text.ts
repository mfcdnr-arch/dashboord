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

/**
 * Убирает слова, которые есть В КАЖДОЙ подписи набора.
 *
 * `distinctLabels` отрезает общее НАЧАЛО и КОНЕЦ, но в госформах общее сидит и
 * в середине: все 63 отделения РЦО называются «Отделение № 1 ГБУ "МФЦ ДНР"
 * г. Мариуполь ул.Ленина, 107» — «ГБУ "МФЦ ДНР"» повторяется у каждого и не
 * различает ничего, зато занимает треть подписи, из-за чего под обрезку
 * попадает как раз номер отделения и город.
 *
 * Слово, встречающееся во ВСЕХ подписях, по определению не различает их — его
 * можно убрать без потери смысла. Знаки-разделители («·», «—») не трогаем: без
 * них имя графы «Ведомство · Услуга · Показатель» рассыпается в кашу.
 *
 * Предохранители те же, что у `distinctLabels`: если после чистки подписи
 * опустели или перестали различаться — возвращаем исходные. Лучше длинно, чем
 * непонятно.
 */
export function dropCommonWords(names: string[]): string[] {
  if (names.length < 2) return names
  const hasLetter = (w: string) => /[\p{L}\p{N}]/u.test(w)
  const words = names.map((n) => n.split(/\s+/).filter(Boolean))
  const common = new Set(
    words[0].filter((w) => hasLetter(w) && words.every((ws) => ws.includes(w))),
  )
  if (!common.size) return names
  const cut = names.map((_n, i) =>
    words[i]
      .filter((w) => !common.has(w))
      .join(' ')
      // Хвосты вроде «… · Выдано,» и осиротевшие разделители по краям.
      .replace(/\s*·\s*·\s*/g, ' · ')
      .replace(/^[\s·,]+|[\s·,]+$/g, '')
      .trim(),
  )
  if (cut.some((s) => !s)) return names
  if (new Set(cut).size !== new Set(names).size) return names
  return cut
}

/** Русское склонение по числу: plural(2, 'период', 'периода', 'периодов').
 *
 * Правило единственное на весь фронт: «есть 2 отчётных периодов» — мелочь,
 * которая читается как небрежность и подрывает доверие к самим цифрам рядом.
 * На бэкенде такой помощник уже живёт (`_describe._plural`) — здесь его
 * зеркало для текстов, которые собираются в интерфейсе.
 */
export function plural(n: number, one: string, few: string, many: string): string {
  const tail = Math.abs(n) % 100
  if (tail >= 11 && tail <= 14) return many
  const last = tail % 10
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}
