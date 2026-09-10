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

/**
 * Ширина строки в пикселях — тем же способом, каким её меряет сам график.
 *
 * ECharts считает ширину подписи через `canvas.measureText`, поэтому и мы
 * меряем так же: проверено на подписях отделений РЦО — SVG отдаёт 160,4px,
 * canvas 160,5px. Это и позволяет заранее знать, сколько места займёт
 * повёрнутая подпись, вместо подобранного числа.
 *
 * В окружении без canvas (юнит-тесты в jsdom) возвращаем оценку по средней
 * ширине знака — она нужна лишь чтобы функция не падала; настоящие числа
 * даёт браузер.
 */
let measureCtx: CanvasRenderingContext2D | null | undefined
export function textWidth(text: string, fontPx = 11, family = 'sans-serif'): number {
  if (measureCtx === undefined) {
    try {
      measureCtx = document.createElement('canvas').getContext('2d')
    } catch {
      measureCtx = null
    }
  }
  if (!measureCtx) return text.length * fontPx * 0.55
  measureCtx.font = `${fontPx}px ${family}`
  return measureCtx.measureText(text).width
}

/** Обрезает подпись (вырезая середину) так, чтобы она уложилась в `maxW` пикселей. */
export function shrinkToWidth(text: string, maxW: number, measure: (s: string) => number): string {
  if (measure(text) <= maxW) return text
  let lo = 4
  let hi = text.length
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (measure(elideMiddle(text, mid)) <= maxW) lo = mid
    else hi = mid - 1
  }
  return elideMiddle(text, lo)
}

/**
 * Полоса под ПОВЁРНУТЫМИ подписями оси — и подписи, обрезанные под эту полосу.
 *
 * 🔴 Раньше полоса задавалась числом (58px). Занимали же подписи столько,
 * сколько занимали: у имён отделений РЦО повёрнутая строка занимает 96px
 * (замер: 170px текста × sin30° + 12,5px высоты × cos30°), и подписи ложились
 * поверх легенды — ровно то наложение, на которое пожаловался заказчик. Числом
 * эту полосу задать нельзя в принципе: она зависит от длины ИМЕНИ, а имена
 * приходят из формы и бывают какими угодно.
 *
 * Поэтому здесь два действия сразу, и второе не менее важно первого:
 *  1. полоса считается по геометрии поворота от РЕАЛЬНОЙ ширины текста;
 *  2. если такая полоса съедает больше отведённой доли высоты, укорачиваются
 *     САМИ подписи, а не полоса. Подпись на оси — подсказка (полное имя есть
 *     во всплывающей подсказке), а место под столбики отдавать нельзя.
 *
 * Наложение при этом невозможно по построению, а не по удачно подобранному
 * числу: сколько подписи занимают, столько под них и зарезервировано.
 */
export function fitRotatedAxis(
  labels: string[],
  o: { fontPx: number; deg: number; maxBand: number; measure: (s: string) => number },
): { labels: string[]; band: number } {
  const rad = (o.deg * Math.PI) / 180
  const sin = Math.abs(Math.sin(rad))
  const cos = Math.abs(Math.cos(rad))
  // Высота строки при 11px — 12,5px (замер по getBBox у ECharts).
  const lineH = o.fontPx * 1.15
  // ECharts отступает от оси до подписи (axisLabel.margin, по умолчанию 8).
  const band = (w: number) => Math.ceil(w * sin + lineH * cos) + 10
  const room = band(Math.max(0, ...labels.map(o.measure)))
  if (room <= o.maxBand || sin < 0.01) return { labels, band: room }
  const allowW = Math.max(24, (o.maxBand - 10 - lineH * cos) / sin)
  const cut = labels.map((s) => shrinkToWidth(s, allowW, o.measure))
  return { labels: cut, band: band(Math.max(0, ...cut.map(o.measure))) }
}
