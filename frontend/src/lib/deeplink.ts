/**
 * Ссылка на конкретное место в системе (п. 6): раздел, отчёт, страница, период.
 *
 * До этого адрес в браузере не менялся ВООБЩЕ — ни router, ни `pushState` в
 * проекте не было, — поэтому прислать коллеге ссылку «этот отчёт, эта
 * страница, этот период» было нельзя: получатель открывал стартовый экран и
 * дальше искал руками.
 *
 * 🔴 **Почему параметры запроса, а не путь.** Путь вида `/dashboards/{id}`
 * здесь невозможен: API проксируется С КОРНЯ примерно по тридцати префиксам,
 * и `dashboards` — один из них (`nginx.locations.conf`, `location ~ ^/(…)`).
 * Проверено живым запросом: `/dashboards/abc` отдаёт **401 application/json**,
 * то есть отвечает бэкенд, а не SPA. Параметры запроса не сталкиваются ни с
 * одним префиксом — ни с нынешними, ни с теми, что появятся позже, — и не
 * требуют ни правки nginx, ни router-библиотеки.
 *
 * Формат: `/?s=<раздел>&d=<дашборд>&p=<страница>&from=…&to=…&row=…&w=<виджет>`
 */

/** Состояние, которое переносится ссылкой. Пустые поля в адрес не пишутся. */
export interface LinkState {
  section?: string
  /** Открытый дашборд и страница внутри него. */
  dashboard?: string
  page?: string
  /** Фильтры страницы — то, ради чего ссылку чаще всего и шлют. */
  from?: string
  to?: string
  row?: string
  /** Виджет, к которому нужно прокрутить и подсветить («посмотри вот сюда»). */
  widget?: string
}

const KEYS: Record<keyof LinkState, string> = {
  section: 's', dashboard: 'd', page: 'p',
  from: 'from', to: 'to', row: 'row', widget: 'w',
}

/** Разобрать адрес в состояние. Мусор игнорируется молча: по чужой или
 *  испорченной ссылке человек должен попасть в рабочую систему, а не в
 *  сообщение об ошибке. */
export function parseLink(search: string): LinkState {
  const q = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const out: LinkState = {}
  for (const [field, key] of Object.entries(KEYS) as [keyof LinkState, string][]) {
    const v = q.get(key)
    if (v) out[field] = v
  }
  return out
}

/** Собрать адрес из состояния. Порядок ключей фиксирован — иначе одна и та же
 *  страница давала бы разные строки, и сравнение «адрес уже такой» ломалось бы,
 *  а история засорялась бы повторами. */
export function buildLink(state: LinkState, pathname = '/'): string {
  const q = new URLSearchParams()
  for (const [field, key] of Object.entries(KEYS) as [keyof LinkState, string][]) {
    const v = state[field]
    if (v) q.set(key, v)
  }
  const s = q.toString()
  return s ? `${pathname}?${s}` : pathname
}

/** Меняется ли ПОЛОЖЕНИЕ в системе, а не только фильтры.
 *
 *  Разница определяет, заводить ли запись в истории браузера: переход в другой
 *  раздел или отчёт — это шаг назад-вперёд, а правка периода — уточнение того
 *  же места. Иначе одна настройка фильтра оставляла бы десяток записей, и
 *  кнопка «назад» переставала бы работать осмысленно. */
export function isNavigation(a: LinkState, b: LinkState): boolean {
  return a.section !== b.section || a.dashboard !== b.dashboard || a.page !== b.page
}

/** Отличаются ли состояния хоть чем-нибудь. */
export function sameLink(a: LinkState, b: LinkState): boolean {
  return (Object.keys(KEYS) as (keyof LinkState)[]).every((k) => (a[k] || '') === (b[k] || ''))
}
