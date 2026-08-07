import { useMemo, useState } from 'react'
import EChartLazy from './EChartLazy'
import { chartColors, useThemeVersion } from '../theme'
import type { FieldSuggestion } from '../api'

/**
 * Черновик дашборда прямо в конструкторе разметки.
 *
 * Смысл: пользователь выбирает столбцы и строки и тут же видит, во что это
 * превратится на дашборде. Раньше результат становился виден только через
 * несколько шагов (выпуск датасета → метрика → виджеты), и понять, правильно
 * ли размечен файл, было нельзя.
 *
 * Ничего не сохраняется и не считается на сервере: рисуем из тех же строк,
 * которые вернул `layout-preview`. Это предпросмотр формы, а не готовый
 * дашборд — на реальном дашборде значения считаются метриками.
 */

interface Props {
  columns: FieldSuggestion[]      // только выбранные показатели
  rows: string[][]                // строки-образцы из layout-preview
  labelColumn: number | null      // где названия строк
  names: Record<number, string>   // переименования пользователя
  totalRows: number
}

/** Строка → число: разрядные пробелы, десятичная запятая, проценты. */
export function parseNum(s: string | undefined): number | null {
  if (!s) return null
  let t = s.replace(/[\s  ]/g, '').replace('%', '')
  if ((t.match(/,/g) || []).length === 1 && !t.includes('.')) t = t.replace(',', '.')
  else t = t.replace(/,/g, '')
  const n = Number(t)
  return t !== '' && Number.isFinite(n) ? n : null
}

const fmt = (n: number) =>
  Math.abs(n) >= 1000 ? n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : String(Math.round(n * 100) / 100)

/**
 * Доли и проценты складывать нельзя — сумма «12,4 + 9,8 + …» смысла не имеет
 * и вводит в заблуждение прямо в момент разметки. Для таких показателей
 * считаем среднее, для остальных — сумму.
 */
const SHARE_RE = /%|доля|удельн|средн/i
export function aggregate(name: string, nums: number[]): { value: number; kind: string } {
  if (!nums.length) return { value: 0, kind: '' }
  if (SHARE_RE.test(name)) {
    return { value: nums.reduce((a, b) => a + b, 0) / nums.length, kind: 'среднее' }
  }
  return { value: nums.reduce((a, b) => a + b, 0), kind: 'сумма' }
}

export default function DashboardDraft({ columns, rows, labelColumn, names, totalRows }: Props) {
  useThemeVersion() // цвета серий берутся из токенов темы — перерисовать при её смене
  const nameOf = (c: FieldSuggestion) => names[c.column_index] ?? c.field_name
  const numeric = useMemo(
    () => columns.filter((c) => c.column_index !== labelColumn && rows.some((r) => parseNum(r[c.column_index]) !== null)),
    [columns, rows, labelColumn],
  )
  const [pickIdx, setPick] = useState<number | null>(null)
  const shown = numeric.find((c) => c.column_index === pickIdx) || numeric[0] || null

  const labels = useMemo(
    () => rows.map((r, i) => (labelColumn !== null ? (r[labelColumn] || '').trim() : '') || `Строка ${i + 1}`),
    [rows, labelColumn],
  )

  if (!numeric.length) {
    return (
      <div style={box}>
        <div style={muted}>
          Среди выбранных столбцов нет числовых — на дашборде показывать будет нечего.
          Проверьте область данных и тип столбцов.
        </div>
      </div>
    )
  }

  const colors = chartColors().palette
  const values = shown ? rows.map((r) => parseNum(r[shown.column_index]) ?? 0) : []
  const single = rows.length === 1

  return (
    <div style={box}>
      {/* KPI-карточки: то, во что превращается каждый выбранный числовой столбец */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: single ? 0 : 16 }}>
        {numeric.map((c, i) => {
          const nums = rows.map((r) => parseNum(r[c.column_index])).filter((n): n is number => n !== null)
          const agg = aggregate(nameOf(c), nums)
          const active = shown?.column_index === c.column_index
          return (
            <button
              key={c.column_index}
              type="button"
              onClick={() => setPick(c.column_index)}
              title={single ? 'Значение показателя' : 'Показать этот показатель на графике'}
              style={{
                ...card,
                // Именно border целиком, а не borderColor поверх: React ругается
                // на смешивание сокращённого и обычного свойства при перерисовке.
                border: `1px solid ${active && !single ? 'var(--accent)' : 'var(--border)'}`,
                cursor: single ? 'default' : 'pointer',
              }}
            >
              <span style={{ ...cardTitle, color: colors[i % colors.length] }}>{nameOf(c)}</span>
              <span style={cardValue}>{fmt(single ? (nums[0] ?? 0) : agg.value)}</span>
              <span style={cardSub}>{single ? 'значение' : `${agg.kind} по ${nums.length} строк.`}</span>
            </button>
          )
        })}
      </div>

      {!single && shown && (
        <>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
            {nameOf(shown)} — по строкам отчёта
          </div>
          <EChartLazy
            height={Math.max(200, Math.min(420, labels.length * 26 + 60))}
            option={{
              grid: { left: 8, right: 16, top: 10, bottom: 8, containLabel: true },
              tooltip: { trigger: 'axis' },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: labels, inverse: true, axisLabel: { width: 210, overflow: 'truncate' } },
              series: [{ type: 'bar', data: values, itemStyle: { color: colors[0] }, barMaxWidth: 22 }],
            }}
          />
          {totalRows > rows.length && (
            <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
              Показаны первые {rows.length} строк из {totalRows}.
            </div>
          )}
        </>
      )}
    </div>
  )
}

const box: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 12, padding: 14, background: 'var(--surface)',
}
const card: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, minWidth: 150, maxWidth: 260,
  border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', background: 'var(--bg)', textAlign: 'left',
}
const cardTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, lineHeight: 1.25,
  display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
}
const cardValue: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: 'var(--text)' }
const cardSub: React.CSSProperties = { fontSize: 11, color: 'var(--text-faint)' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 }
