import { useMemo, useState } from 'react'
import EChartLazy from './EChartLazy'
import { chartColors, useThemeVersion } from '../theme'
import { elideMiddle } from '../lib/text'
import { logScaleAdvice } from '../lib/format'
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
  let t = s.replace(/[\s  ]/g, '').replace('%', '')
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

/**
 * Годятся ли названия строк как подписи на графике.
 *
 * В формах-приложениях слева стоит «№ п/п», и график «по строкам» выродится
 * в безымянные столбики. Тогда осмысленный разрез — сами показатели.
 */
export function labelsAreUseful(rows: string[][], labelColumn: number | null): boolean {
  if (labelColumn === null || rows.length < 2) return false
  const values = rows.map((r) => (r[labelColumn] || '').trim()).filter(Boolean)
  const distinct = new Set(values)
  if (distinct.size < 2) return false
  return ![...distinct].every((v) => parseNum(v) !== null)
}

/**
 * Нужна ли логарифмическая шкала.
 *
 * На одном графике живут «110 000 записавшихся» и «183 подключённых МФЦ» —
 * на линейной шкале второй столбик вырождается в полоску толщиной в пиксель.
 * Логарифм показывает оба, но существует только для строго положительных
 * значений: ноль и минус на такой шкале не изобразить, поэтому там остаёмся
 * на линейной и вместо длины столбика полагаемся на подписанное число.
 */
// Переехала в lib/format.ts — той же логикой пользуется виджет «Сравнение»
// на дашборде. Реэкспорт оставлен: на неё ссылаются тесты черновика.
export { logScaleAdvice }

export default function DashboardDraft({ columns, rows, labelColumn, names, totalRows }: Props) {
  useThemeVersion() // цвета серий берутся из токенов темы — перерисовать при её смене
  const nameOf = (c: FieldSuggestion) => names[c.column_index] ?? c.field_name
  const numeric = useMemo(
    () => columns.filter((c) => c.column_index !== labelColumn && rows.some((r) => parseNum(r[c.column_index]) !== null)),
    [columns, rows, labelColumn],
  )
  const [pickIdx, setPick] = useState<number | null>(null)
  const shown = numeric.find((c) => c.column_index === pickIdx) || numeric[0] || null

  const useful = useMemo(() => labelsAreUseful(rows, labelColumn), [rows, labelColumn])
  const [byRowsChoice, setByRows] = useState<boolean | null>(null)
  const byRows = byRowsChoice ?? useful
  const [logScale, setLogScale] = useState<boolean | null>(null)

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
  const single = rows.length === 1

  // Значения карточек считаем один раз: они же идут в график «по показателям».
  const totals = numeric.map((c) => {
    const nums = rows.map((r) => parseNum(r[c.column_index])).filter((n): n is number => n !== null)
    return { col: c, nums, ...aggregate(nameOf(c), nums) }
  })

  const rowLabels = rows.map((r, i) => (labelColumn !== null ? (r[labelColumn] || '').trim() : '') || `Строка ${i + 1}`)
  const chart = byRows && shown
    ? {
        title: `${nameOf(shown)} — по строкам отчёта`,
        labels: rowLabels.map((l) => elideMiddle(l, 42)),
        values: rows.map((r) => parseNum(r[shown.column_index]) ?? 0),
        full: rowLabels,
      }
    : {
        title: 'Показатели отчёта',
        labels: totals.map((t) => elideMiddle(nameOf(t.col), 42)),
        values: totals.map((t) => t.value),
        full: totals.map((t) => nameOf(t.col)),
      }

  const { helps: logHelps, spread } = logScaleAdvice(chart.values)
  const useLog = logScale ?? logHelps

  return (
    <div style={box}>
      {/* KPI-карточки: то, во что превращается каждый выбранный числовой столбец */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: single ? 0 : 16 }}>
        {totals.map((t, i) => {
          const active = shown?.column_index === t.col.column_index && byRows
          const full = nameOf(t.col)
          return (
            <button
              key={t.col.column_index}
              type="button"
              onClick={() => setPick(t.col.column_index)}
              title={full}
              style={{
                ...card,
                // Именно border целиком, а не borderColor поверх: React ругается
                // на смешивание сокращённого и обычного свойства при перерисовке.
                border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                cursor: single || !byRows ? 'default' : 'pointer',
              }}
            >
              <span style={{ ...cardTitle, color: colors[i % colors.length] }}>{elideMiddle(full, 110)}</span>
              <span style={cardValue}>{fmt(single ? (t.nums[0] ?? 0) : t.value)}</span>
              <span style={cardSub}>{single ? 'значение' : `${t.kind} по ${t.nums.length} строк.`}</span>
            </button>
          )
        })}
      </div>

      {!single && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{chart.title}</span>
            <span style={{ display: 'flex', gap: 4, marginLeft: 'auto', flexWrap: 'wrap' }}>
              {logHelps && (
                <>
                  <button type="button" style={{ ...tab, ...(!useLog ? tabActive : {}) }}
                    title="Обычная шкала: показатели сравнимы по длине столбика, но маленькие могут быть не видны"
                    onClick={() => setLogScale(false)}>
                    линейная
                  </button>
                  <button type="button" style={{ ...tab, ...(useLog ? tabActive : {}) }}
                    title="Логарифмическая шкала: видно и сотни, и сотни тысяч, но длина столбиков уже не пропорциональна значениям"
                    onClick={() => setLogScale(true)}>
                    логарифмическая
                  </button>
                </>
              )}
              {useful && (
                <>
                  <button type="button" style={{ ...tab, ...(byRows ? tabActive : {}) }} onClick={() => setByRows(true)}>
                    по строкам
                  </button>
                  <button type="button" style={{ ...tab, ...(!byRows ? tabActive : {}) }} onClick={() => setByRows(false)}>
                    по показателям
                  </button>
                </>
              )}
            </span>
          </div>
          {useLog && (
            <div style={{ fontSize: 11, color: 'var(--text-faint)', marginBottom: 2 }}>
              Значения различаются в {Math.round(spread)} раз, поэтому шкала логарифмическая —
              иначе маленькие показатели не видны. Точные числа подписаны у столбиков.
            </div>
          )}
          <EChartLazy
            height={Math.max(220, Math.min(700, chart.labels.length * 46 + 60))}
            option={{
              // Справа оставляем место под число у конца столбика.
              grid: { left: 8, right: 72, top: 10, bottom: 8, containLabel: true },
              // Подпись в подсказке — ПОЛНАЯ: на оси имя может не поместиться,
              // а различие показателей часто именно в хвосте.
              tooltip: {
                trigger: 'axis',
                formatter: (p: any) => {
                  const it = Array.isArray(p) ? p[0] : p
                  return `${chart.full[it.dataIndex]}<br/><b>${fmt(it.value)}</b>`
                },
              },
              // hideOverlap: на узкой колонке деления логарифмической шкалы
              // («1 10 100 1 000 10 000 100 000») наезжают друг на друга
              // и превращаются в кашу — лишние лучше не рисовать.
              xAxis: { type: useLog ? 'log' : 'value', axisLabel: { hideOverlap: true } },
              yAxis: {
                type: 'category', data: chart.labels, inverse: true,
                axisLabel: {
                  // interval: 0 обязателен: иначе ECharts прячет часть подписей,
                  // чтобы они не налезали друг на друга, и столбик остаётся
                  // безымянным — именно это и увидел заказчик у верхнего.
                  interval: 0,
                  width: 230, overflow: 'break', lineHeight: 13, fontSize: 11,
                },
              },
              series: [{
                type: 'bar', data: chart.values, barMaxWidth: 22,
                // Число у столбика: на логарифмической шкале длина обманчива,
                // да и короткий столбик иначе не прочитать.
                label: {
                  show: true, position: 'right', fontSize: 11,
                  formatter: (p: any) => fmt(p.value),
                },
                itemStyle: byRows
                  ? { color: colors[0] }
                  : { color: (p: any) => colors[p.dataIndex % colors.length] },
              }],
            }}
          />
          {byRows && totalRows > rows.length && (
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
  display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, minWidth: 170, maxWidth: 300,
  border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', background: 'var(--bg)', textAlign: 'left',
}
const cardTitle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, lineHeight: 1.3, whiteSpace: 'normal',
}
const cardValue: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: 'var(--text)' }
const cardSub: React.CSSProperties = { fontSize: 11, color: 'var(--text-faint)' }
const muted: React.CSSProperties = { color: 'var(--text-muted)', fontSize: 13 }
const tab: React.CSSProperties = {
  border: '1px solid var(--border)', borderRadius: 8, background: 'transparent',
  color: 'var(--text-muted)', fontSize: 12, padding: '3px 10px', cursor: 'pointer',
}
const tabActive: React.CSSProperties = {
  border: '1px solid var(--accent)', background: 'var(--accent-weak-bg)', color: 'var(--accent)',
}
