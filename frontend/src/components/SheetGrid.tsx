import { useRef, useState } from 'react'

/**
 * Лист документа «как в оригинале» с выбором мышью.
 *
 * Объединённые ячейки рисуются настоящими rowSpan/colSpan — поэтому предпросмотр
 * совпадает с исходным файлом, а не выглядит рассыпанной сеткой. Нумерация строк
 * и буквы столбцов — как в Excel, чтобы сверять с оригиналом глазами.
 *
 * Что можно делать мышью:
 *   • протянуть по ячейкам — задать область данных (одиночный клик не сбрасывает
 *     область: слишком легко промахнуться и потерять выделение);
 *   • кликнуть букву столбца — включить/исключить столбец;
 *   • кликнуть номер строки — включить/исключить строку;
 *   • кликнуть ◉ в шапке столбца — назначить его столбцом названий строк;
 *   • в режиме «отдельные ячейки» — кликнуть ячейку и назвать показатель.
 */

export type Rect = [number, number, number, number] // r1, c1, r2, c2 — включительно

export interface PickedCell { row: number; col: number; field_name: string; field_code: string }

interface Props {
  rows: string[][]
  merges: number[][]
  rect: Rect
  headerRows: number
  labelCol: number | null
  excludedCols: Set<number>
  excludedRows: Set<number>
  mode: 'table' | 'cells'
  picked: PickedCell[]
  onRect: (r: Rect) => void
  onToggleCol: (c: number) => void
  onToggleRow: (r: number) => void
  onLabelCol: (c: number) => void
  onPickCell: (row: number, col: number, value: string) => void
}

/** Копия сетки с развёрнутыми объединениями — для подстановки имён из шапки. */
export function fillMerges(rows: string[][], merges: number[][]): string[][] {
  const out = rows.map((r) => [...r])
  for (const [r1, c1, r2, c2] of merges) {
    const v = out[r1]?.[c1]
    if (!v) continue
    for (let r = r1; r <= r2 && r < out.length; r++) {
      for (let c = c1; c <= c2 && c < out[r].length; c++) out[r][c] = v
    }
  }
  return out
}

export function colName(i: number): string {
  let s = ''
  let n = i + 1
  while (n > 0) {
    const m = (n - 1) % 26
    s = String.fromCharCode(65 + m) + s
    n = Math.floor((n - 1) / 26)
  }
  return s
}

export default function SheetGrid(props: Props) {
  const { rows, merges, rect, headerRows, labelCol, excludedCols, excludedRows, mode, picked } = props
  const width = rows.reduce((w, r) => Math.max(w, r.length), 0)
  const [r1, c1, , c2] = rect

  // Ячейки, накрытые объединением: рисует их левая верхняя, остальные пропускаем.
  const span = new Map<string, [number, number]>()
  const covered = new Set<string>()
  for (const [mr1, mc1, mr2, mc2] of merges) {
    span.set(`${mr1}:${mc1}`, [mr2 - mr1 + 1, mc2 - mc1 + 1])
    for (let r = mr1; r <= mr2; r++) {
      for (let c = mc1; c <= mc2; c++) if (r !== mr1 || c !== mc1) covered.add(`${r}:${c}`)
    }
  }

  const pickedAt = new Map(picked.map((p) => [`${p.row}:${p.col}`, p]))

  // Протягивание области данных
  const anchor = useRef<[number, number] | null>(null)
  const [drag, setDrag] = useState<Rect | null>(null)

  function beginDrag(r: number, c: number) {
    if (mode !== 'table') return
    anchor.current = [r, c]
    setDrag([r, c, r, c])
  }
  function overCell(r: number, c: number) {
    if (!anchor.current) return
    const [ar, ac] = anchor.current
    setDrag([Math.min(ar, r), Math.min(ac, c), Math.max(ar, r), Math.max(ac, c)])
  }
  function endDrag() {
    const d = drag
    anchor.current = null
    setDrag(null)
    // Одиночный клик область не меняет — иначе промах мышью стирал бы разметку.
    if (d && (d[2] > d[0] || d[3] > d[1])) props.onRect(d)
  }

  const shown = drag || rect
  const inArea = (r: number, c: number) => r >= shown[0] && r <= shown[2] && c >= shown[1] && c <= shown[3]
  const isHeaderRow = (r: number) => r >= r1 && r < r1 + headerRows
  const dropped = (r: number, c: number) =>
    !inArea(r, c) || excludedCols.has(c) || (excludedRows.has(r) && !isHeaderRow(r))

  return (
    <div style={wrap} onMouseUp={endDrag} onMouseLeave={endDrag}>
      <table style={table}>
        <thead>
          <tr>
            <th style={{ ...corner, ...sticky }} />
            {Array.from({ length: width }, (_, c) => {
              const off = excludedCols.has(c) || c < c1 || c > c2
              return (
                <th key={c} style={{ ...colHead, opacity: off ? 0.4 : 1 }}>
                  <button
                    type="button" style={colBtn} title={off ? 'Включить столбец' : 'Исключить столбец'}
                    onClick={() => props.onToggleCol(c)}
                  >
                    {colName(c)}
                  </button>
                  <button
                    type="button" style={{ ...radio, color: labelCol === c ? 'var(--accent)' : 'var(--text-faint)' }}
                    title="Столбец с названиями строк" onClick={() => props.onLabelCol(c)}
                  >
                    {labelCol === c ? '◉' : '○'}
                  </button>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              <th style={{ ...rowHead, ...sticky, opacity: excludedRows.has(r) ? 0.4 : 1 }}>
                <button
                  type="button" style={colBtn} title={excludedRows.has(r) ? 'Включить строку' : 'Исключить строку'}
                  onClick={() => props.onToggleRow(r)}
                >
                  {r + 1}
                </button>
              </th>
              {Array.from({ length: width }, (_, c) => {
                if (covered.has(`${r}:${c}`)) return null
                const [rs, cs] = span.get(`${r}:${c}`) || [1, 1]
                const value = row[c] ?? ''
                const pick = pickedAt.get(`${r}:${c}`)
                const off = dropped(r, c)
                return (
                  <td
                    key={c}
                    rowSpan={rs}
                    colSpan={cs}
                    onMouseDown={() => beginDrag(r, c)}
                    onMouseEnter={() => overCell(r, c)}
                    onClick={() => mode === 'cells' && props.onPickCell(r, c, value)}
                    title={pick ? `Показатель: ${pick.field_name}` : value}
                    style={{
                      ...cell,
                      cursor: mode === 'cells' ? 'pointer' : 'cell',
                      background: pick
                        ? 'var(--accent-weak-bg)'
                        : isHeaderRow(r) && inArea(r, c)
                          ? 'var(--surface-alt, rgba(127,127,127,0.10))'
                          : labelCol === c && inArea(r, c)
                            ? 'rgba(127,127,127,0.05)'
                            : 'transparent',
                      opacity: off ? 0.35 : 1,
                      outline: pick ? '2px solid var(--accent)' : undefined,
                    }}
                  >
                    {pick && <span style={badge}>{pick.field_name}</span>}
                    {value}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const wrap: React.CSSProperties = {
  overflow: 'auto', maxHeight: '60vh', border: '1px solid var(--border)', borderRadius: 10,
  userSelect: 'none',
}
const table: React.CSSProperties = { borderCollapse: 'separate', borderSpacing: 0, fontSize: 12 }
const sticky: React.CSSProperties = { position: 'sticky', left: 0, zIndex: 2, background: 'var(--bg)' }
const corner: React.CSSProperties = {
  minWidth: 34, borderRight: '1px solid var(--border)', borderBottom: '1px solid var(--border)',
  position: 'sticky', top: 0, zIndex: 3,
}
const colHead: React.CSSProperties = {
  position: 'sticky', top: 0, zIndex: 1, background: 'var(--bg)', padding: '2px 4px',
  borderBottom: '1px solid var(--border)', borderRight: '1px solid var(--border-faint)',
  whiteSpace: 'nowrap', fontWeight: 500,
}
const rowHead: React.CSSProperties = {
  padding: '2px 6px', borderRight: '1px solid var(--border)', borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-muted)', fontWeight: 400, textAlign: 'right',
}
const colBtn: React.CSSProperties = {
  border: 'none', background: 'transparent', cursor: 'pointer', font: 'inherit',
  color: 'var(--text-muted)', padding: '0 2px',
}
const radio: React.CSSProperties = { border: 'none', background: 'transparent', cursor: 'pointer', padding: 0 }
const cell: React.CSSProperties = {
  border: '1px solid var(--border-faint)', padding: '3px 6px', maxWidth: 260,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'top',
}
const badge: React.CSSProperties = {
  display: 'block', fontSize: 10, color: 'var(--accent)', fontWeight: 600, lineHeight: 1.2,
}
