/**
 * Общие части таблиц: сортируемый заголовок и проваливание в строку.
 *
 * До них и то, и другое было доступно ТОЛЬКО мышью: заголовок — `<th>` с
 * `onClick`, строка — `<tr>` с `onClick`. С клавиатуры до них не добраться
 * вовсе (Tab по ним не ходит), а диктор не сообщал ни что столбец сортируем,
 * ни в каком он порядке. При этом таблица — главный экран для разбора цифр:
 * отсортировать и провалиться в строку нужно чаще всего.
 *
 * Приём тот же, что с окнами: одна общая часть, а не обход всех мест.
 */

export const SORT_HINT =
  'Сортировать по этому столбцу: ▲ по возрастанию, ▼ по убыванию, третий клик — сброс'

export type SortState = { col: string; dir: 1 | -1 } | null

/** Кнопка внутри ячейки: без рамки и фона, чтобы заголовок выглядел как был. */
const bare: React.CSSProperties = {
  border: 'none', background: 'none', padding: 0, margin: 0, font: 'inherit',
  color: 'inherit', cursor: 'pointer', textAlign: 'inherit' as const, width: '100%',
}

export function sortArrow(sort: SortState, col: string): string {
  return sort?.col === col ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''
}

/**
 * Заголовок сортируемого столбца.
 *
 * `aria-sort` — то, чем диктор сообщает ТЕКУЩИЙ порядок: стрелка ▲ рядом с
 * текстом видна только глазами. Само нажатие — обычная кнопка, поэтому Enter
 * и пробел работают без своей обработки клавиш.
 */
export function SortableTh(
  { sort, col, onSort, style, title, children }: {
    sort: SortState
    col: string
    onSort: (col: string) => void
    style?: React.CSSProperties
    title?: string
    children: React.ReactNode
  },
) {
  const dir = sort?.col === col ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'
  return (
    <th scope="col" aria-sort={dir} style={{ ...style, cursor: 'pointer', userSelect: 'none' }}>
      <button type="button" style={bare} onClick={() => onSort(col)} title={title ?? SORT_HINT}>
        {children}{sortArrow(sort, col)}
      </button>
    </th>
  )
}

/**
 * Название строки, по которому проваливаются в неё.
 *
 * Кнопкой сделано НАЗВАНИЕ, а не строка целиком: у `<tr>` нет своей роли, и
 * чтобы он принимал клавиатуру, пришлось бы навешивать `tabIndex`, роль и
 * обработку Enter/Space вручную — то есть изображать кнопку. Название строки
 * и есть то, что человек читает глазами перед тем, как провалиться.
 *
 * Клик по всей строке при этом сохранён: мышью привычно попадать куда угодно.
 */
export function RowPickCell(
  { label, onPick, style, title, children }: {
    label: string
    /** Не задан — строка не проваливается (отчёт, нет прав): обычная ячейка. */
    onPick?: (row: string) => void
    style?: React.CSSProperties
    /** Своя подсказка там, где строка ведёт не на страницу по строке,
     *  а куда-то ещё: обещать не то, что произойдёт, хуже, чем молчать. */
    title?: string
    children?: React.ReactNode
  },
) {
  const content = children ?? label
  return (
    <th scope="row" style={{ ...style, fontWeight: 600, textAlign: 'left' }}>
      {onPick
        ? (
          <button
            type="button" style={{ ...bare, color: 'var(--accent-text)' }}
            onClick={(e) => { e.stopPropagation(); onPick(label) }}
            title={title ?? `Показать всю страницу по строке «${label}»`}
          >{content}</button>
        )
        : content}
    </th>
  )
}

/**
 * Первая ячейка строки, которая что-то ПЕРЕКЛЮЧАЕТ: раскрывает подробности
 * или фильтрует список по себе.
 *
 * Отличается от [RowPickCell] не только клавиатурой: состояние переключателя
 * надо СООБЩИТЬ. `aria-expanded` говорит, раскрыта ли строка, `aria-pressed` —
 * выбрана ли она как фильтр; глазами это видно по «▸/▾» и подсветке, а
 * диктору — только из этих атрибутов.
 */
export function RowToggleCell(
  { onToggle, expanded, pressed, title, style, children }: {
    onToggle: () => void
    /** Строка раскрывает подробности под собой. */
    expanded?: boolean
    /** Строка работает переключателем (фильтр по себе). */
    pressed?: boolean
    title?: string
    style?: React.CSSProperties
    children: React.ReactNode
  },
) {
  return (
    <th scope="row" style={{ ...style, fontWeight: 600, textAlign: 'left' }}>
      <button
        type="button" style={{ ...bare, color: 'var(--accent-text)' }} title={title}
        onClick={(e) => { e.stopPropagation(); onToggle() }}
        {...(expanded !== undefined ? { 'aria-expanded': expanded } : {})}
        {...(pressed !== undefined ? { 'aria-pressed': pressed } : {})}
      >{children}</button>
    </th>
  )
}
