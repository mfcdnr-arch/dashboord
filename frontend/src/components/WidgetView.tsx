import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { EChartsOption } from 'echarts'
import { getWidgetData, getWidgetDrill } from '../api'
import { chartColors, useThemeVersion } from '../theme'
import EChart from './EChartLazy'
import FitText from './dashboards/FitText'
import { fmtNumber as fmt } from '../lib/format'

// Отрисовка данных виджета: KPI/таблица/план-факт — HTML, столбцы/линия/круговая —
// ECharts. По кнопке «подробнее» — drill (прозрачность): формула метрики + первичные строки.


// Дата актуальности данных (as_of) в формате ДД.ММ.ГГГГ.
function fmtAsOf(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU')
}

// Высота графика под РЕАЛЬНО доступное место в карточке.
// Раньше высота была константой: как только под графиком добавилась вторая строка
// итогов, содержимое перестало помещаться (276px против 192px), карточка включила
// прокрутку и показала только нижнюю часть оси — линия графика уехала из виду.
// Числа важнее картинки, поэтому ужимается график, а не подписи.
function useFitHeight(base: number) {
  const box = useRef<HTMLDivElement>(null)
  const labels = useRef<HTMLDivElement>(null)
  const [h, setH] = useState(base)

  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    // Ограничивает высоту не прямой родитель, а карточка виджета выше по дереву;
    // между ними лежат и другие блоки («подробнее», «данные на»), которые тоже
    // занимают место. Поэтому меряем не «сколько осталось», а фактическое
    // переполнение карточки и ужимаем график ровно на него.
    let scroller: HTMLElement | null = el.parentElement
    while (scroller && getComputedStyle(scroller).overflowY === 'visible') scroller = scroller.parentElement
    if (!scroller || !scroller.clientHeight) return // предпросмотр в форме: высота не ограничена

    const calc = () => {
      const s = scroller as HTMLElement
      const over = s.scrollHeight - s.clientHeight
      setH((cur) => {
        if (over > 0) return Math.max(MIN_CHART_H, cur - over)
        if (cur < base) return Math.min(base, cur + Math.max(0, s.clientHeight - s.scrollHeight))
        return cur
      })
    }
    calc()
    const ro = new ResizeObserver(calc)
    ro.observe(scroller)
    if (labels.current) ro.observe(labels.current)
    return () => ro.disconnect()
  }, [base])

  return { box, labels, h }
}
// Ниже этого графику нельзя: на 84px даже три деления оси налезали друг на друга.
// Если содержимое всё равно не помещается, карточка включит прокрутку — это
// честнее, чем показать нечитаемый график.
const MIN_CHART_H = 118

// Подпись периода на графике динамики. Периоды приходят как «2026-07-22»
// (дата выпуска) либо «2026-07» (месяц) — машинный вид на оси читается плохо.
function fmtPeriod(p: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(p)) return fmtAsOf(p)
  const m = /^(\d{4})-(\d{2})$/.exec(p)
  return m ? `${m[2]}.${m[1]}` : p
}

// Палитра серий — из CSS-токенов темы (см. theme.css: --chart-*); при смене темы
// Body перерисовывается (useThemeVersion) и графики пересобираются с новыми цветами.
function chartOption(data: any): EChartsOption {
  const C = chartColors()
  const cats: string[] = data.categories || []
  const vals: number[] = data.values || []
  if (data.type === 'pie') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{ type: 'pie', radius: ['35%', '70%'], data: cats.map((c, i) => ({ name: c, value: vals[i] })),
        label: { fontSize: 11 }, color: C.palette }],
    }
  }
  const isLine = data.type === 'line'
  return {
    grid: { left: 40, right: 12, top: 12, bottom: cats.some((c) => c.length > 6) ? 46 : 24 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: cats.some((c) => c.length > 6) ? 30 : 0, fontSize: 11 } },
    yAxis: { type: 'value' },
    series: [{ type: isLine ? 'line' : 'bar', data: vals, smooth: isLine,
      itemStyle: { color: C.c1 }, lineStyle: { color: C.c1, width: 2 }, areaStyle: isLine ? { opacity: 0.08 } : undefined,
      barMaxWidth: 40 }],
  }
}

export default function WidgetView({ widgetId, reloadKey, showDrill = true, from, to, row, onPick, batched, injData, injError }: { widgetId: string; reloadKey?: number; showDrill?: boolean; from?: string; to?: string; row?: string; onPick?: (name: string) => void; batched?: boolean; injData?: any; injError?: string }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [drill, setDrill] = useState<any | null>(null)

  useEffect(() => {
    // Батч-режим: данные приходят от родителя (1 запрос на всю страницу) — не фетчим сами.
    if (batched) {
      setData(injData ?? null)
      setError(injError ?? null)
      return
    }
    setData(null); setError(null)
    getWidgetData(widgetId, from, to, row).then(setData).catch((e) => setError((e as Error).message))
  }, [widgetId, reloadKey, from, to, row, batched, injData, injError])

  const openDrill = () => getWidgetDrill(widgetId).then(setDrill).catch((e) => setError((e as Error).message))

  const alert = data?.alert
  return (
    <div style={alert ? { borderLeft: `4px solid ${alert.color}`, background: alert.bg, borderRadius: 6, padding: '6px 8px', margin: '-2px 0' } : undefined}>
      {error && <div style={errBox}>{error}</div>}
      {!data && !error && <div style={{ color: '#9aa4b2', fontSize: 13 }}>Загрузка…</div>}
      {alert && (
        <div style={{ display: 'inline-block', fontSize: 11, fontWeight: 600, color: alert.color,
          background: '#fff', border: `1px solid ${alert.color}`, borderRadius: 10, padding: '1px 8px', marginBottom: 6 }}
          title="Сработал порог KPI-алерта">⚠ {alert.label}</div>
      )}
      {data && <Body data={data} onPick={onPick} />}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {data && showDrill && data.type !== 'text' && data.type !== 'image' && (
          <button style={drillBtn} onClick={openDrill} title="Из чего собран показатель">🔍 подробнее</button>
        )}
        {data?.as_of && (
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }} title="Дата актуальности данных (активный выпуск датасета)">
            🕓 данные на {fmtAsOf(data.as_of)}
          </span>
        )}
        {data?.sources && (
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }} title="У виджета несколько источников — единой даты свежести нет, у каждого своя">
            🕓 {data.sources.map((s: any) => `${s.label}: ${s.as_of ? fmtAsOf(s.as_of) : '—'}`).join(' · ')}
          </span>
        )}
      </div>
      {drill && <DrillModal drill={drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

// Рендер тела виджета по готовым данным — используется в конструкторе для предпросмотра.
export function WidgetPreviewBody({ data }: { data: any }) {
  return <Body data={data} />
}

// Цель/бенчмарк под показателем: значение цели + % достижения (зелёный при ≥100%).
function TargetLine({ data }: { data: any }) {
  if (data.target == null) return null
  const pct = data.target_pct
  const reached = pct != null && pct >= 100
  return (
    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
      {data.target_label || 'Цель'}: <b style={{ color: 'var(--text-2)' }}>{fmt(data.target)}</b>
      {pct != null && <span style={{ marginLeft: 6, color: reached ? 'var(--success)' : 'var(--warn)', fontWeight: 600 }}>· {fmt(pct)}%{reached ? ' ✓' : ''}</span>}
    </div>
  )
}

type SortState = { col: string; dir: 1 | -1 } | null

// Сортировка по клику на заголовок столбца (3 состояния: ▲ → ▼ → сброс) + поиск
// по значениям — общее для table/pivot (виджеты становятся длинными без этого).
function sortRows<T extends Record<string, unknown>>(rows: T[], sort: SortState, getVal: (r: T, col: string) => unknown): T[] {
  if (!sort) return rows
  const { col, dir } = sort
  return [...rows].sort((a, b) => {
    const av = getVal(a, col); const bv = getVal(b, col)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv), 'ru') * dir
  })
}
function toggleSort(setSort: (f: (s: SortState) => SortState) => void, col: string) {
  setSort((s) => (s && s.col === col ? (s.dir === 1 ? { col, dir: -1 } : null) : { col, dir: 1 }))
}
function sortArrow(sort: SortState, col: string): string {
  return sort?.col === col ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''
}
const searchInput: React.CSSProperties = {
  height: 30, padding: '0 10px', borderRadius: 6, border: '1px solid var(--border)',
  background: 'var(--surface)', color: 'var(--text)', fontSize: 12, width: 220, marginBottom: 8,
}
const sortableTh: React.CSSProperties = { cursor: 'pointer', userSelect: 'none' }
// Значок ▲/▼ у заголовка ничего не объясняет сам по себе — подсказка при наведении
// говорит, что это сортировка и что делает повторный клик.
const SORT_HINT = 'Сортировать по этому столбцу: ▲ по возрастанию, ▼ по убыванию, третий клик — сброс'

function Body({ data, onPick }: { data: any; onPick?: (name: string) => void }) {
  useThemeVersion() // перерисовка при смене темы: цвета серий берутся из токенов
  const C = chartColors()
  const [tableSearch, setTableSearch] = useState('')
  const [tableSort, setTableSort] = useState<SortState>(null)
  const [pivotSearch, setPivotSearch] = useState('')
  const [pivotSort, setPivotSort] = useState<SortState>(null)
  // Хук объявлен до ветвления по типу виджета: тип может смениться при правке
  // виджета, а порядок хуков между рендерами меняться не должен.
  const fit = useFitHeight(196)
  if (data.type === 'text') {
    const align = data.align === 'center' ? 'center' : 'left'
    if (!data.heading && !data.body) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Пустая аннотация</div>
    return (
      <div style={{ textAlign: align }}>
        {data.heading && <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>{data.heading}</div>}
        {data.body && <div style={{ fontSize: 14, color: 'var(--text-2)', marginTop: data.heading ? 4 : 0, whiteSpace: 'pre-wrap' }}>{data.body}</div>}
      </div>
    )
  }
  if (data.type === 'image') {
    if (!data.url) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Не указан URL картинки</div>
    return (
      <div style={{ textAlign: 'center' }}>
        <img src={data.url} alt={data.caption || ''} style={{ maxWidth: '100%', maxHeight: 220, objectFit: data.fit === 'cover' ? 'cover' : 'contain' }} />
        {data.caption && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{data.caption}</div>}
      </div>
    )
  }
  if (data.type === 'kpi') {
    const kpiText = fmt(data.value) + (data.unit ? ' ' + data.unit : '')
    return (
      <div>
        <FitText size={30} title={kpiText} style={{ fontWeight: 700, color: data.alert?.color || 'var(--accent)' }}>{fmt(data.value)}
          {data.unit && <span style={{ fontSize: '0.5em', color: 'var(--text-muted)', marginLeft: 6 }}>{data.unit}</span>}
        </FitText>
        <TargetLine data={data} />
      </div>
    )
  }
  if (data.type === 'gauge') {
    const max = data.max || 100
    const color = data.alert?.color || C.c1
    const opt: EChartsOption = {
      series: [{
        type: 'gauge', min: 0, max,
        progress: { show: true, width: 12, itemStyle: { color } },
        axisLine: { lineStyle: { width: 12, color: [[1, '#eef0f3']] } },
        axisTick: { show: false },
        splitLine: { length: 8, lineStyle: { color: '#c9ccd1' } },
        axisLabel: { fontSize: 10, color: '#9aa4b2', distance: 12 },
        pointer: { itemStyle: { color } },
        title: { show: false },
        detail: {
          valueAnimation: true, fontSize: 22, fontWeight: 700, color, offsetCenter: [0, '58%'],
          formatter: (v: number) => fmt(v) + (data.unit ? ' ' + data.unit : ''),
        },
        data: [{ value: data.value ?? 0 }],
      }],
    }
    return <div><EChart option={opt} height={190} /><div style={{ marginTop: -14 }}><TargetLine data={data} /></div></div>
  }
  if (data.type === 'plan_fact') {
    const pct = data.pct
    return (
      <div style={{ fontSize: 14 }}>
        <div style={{ display: 'flex', gap: 18 }}>
          <div><div style={muted}>План</div><b>{fmt(data.plan)}</b></div>
          <div><div style={muted}>Факт</div><b>{fmt(data.fact)}</b></div>
          <div><div style={muted}>Δ</div><b style={{ color: data.delta >= 0 ? 'var(--success)' : 'var(--danger)' }}>{data.delta >= 0 ? '+' : ''}{fmt(data.delta)}</b></div>
        </div>
        {pct != null && (
          <div style={{ marginTop: 8 }}>
            <div style={{ height: 10, background: 'var(--border-faint)', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: data.alert?.color || (pct >= 100 ? 'var(--success)' : 'var(--accent)') }} />
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>Выполнение: <b>{fmt(pct)}%</b></div>
          </div>
        )}
      </div>
    )
  }
  if (data.type === 'table') {
    const cols: string[] = data.columns || []
    let rows: any[] = data.rows || []
    if (tableSearch.trim()) {
      const s = tableSearch.trim().toLowerCase()
      rows = rows.filter((r) => String(r.row ?? '').toLowerCase().includes(s) || cols.some((c) => String(r[c] ?? '').toLowerCase().includes(s)))
    }
    rows = sortRows(rows, tableSort, (r, c) => (c === '__row' ? r.row : r[c]))
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <input style={searchInput} placeholder="🔍 Поиск по таблице…" value={tableSearch} onChange={(e) => setTableSearch(e.target.value)} />
          <span style={{ fontSize: 11, color: 'var(--text-faint)', marginBottom: 8 }}>
            клик по заголовку столбца сортирует: ▲ по возрастанию, ▼ по убыванию, третий клик — сброс
          </span>
        </div>
        <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>
            <th style={{ ...th, ...sortableTh }} title={SORT_HINT} onClick={() => toggleSort(setTableSort, '__row')}>Строка{sortArrow(tableSort, '__row')}</th>
            {/* Заголовок — человеческое имя показателя; код остаётся ключом
                данных и подсказкой, чтобы можно было сверить с формулой. */}
            {cols.map((c: string) => (
              <th key={c} style={{ ...th, ...sortableTh }} title={`${SORT_HINT}\nКод столбца: ${c}`}
                onClick={() => toggleSort(setTableSort, c)}>
                {(data.column_titles?.[c] as string) || c}{sortArrow(tableSort, c)}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td style={td} colSpan={cols.length + 1}>Ничего не найдено</td></tr>}
            {rows.map((r: any, i: number) => (
              <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                {cols.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    )
  }
  if (data.type === 'dynamics') {
    const periods: string[] = data.periods || []
    if (periods.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных за период</div>
    const series: any[] = [{ type: 'line', name: 'Значение', data: data.values, smooth: true, itemStyle: { color: C.c1 },
      lineStyle: { color: C.c1, width: 2 }, areaStyle: { opacity: 0.08 } }]
    // Линейный тренд (наложение): прямая по концам от бэкенда, интерполируем по периодам.
    if (data.trend && periods.length >= 2) {
      const [s, e] = data.trend
      const n = periods.length
      const line = periods.map((_, i) => s + (e - s) * i / (n - 1))
      series.push({ type: 'line', name: 'Тренд', data: line, smooth: false, symbol: 'none',
        lineStyle: { color: '#c69b2f', width: 2, type: 'dashed' } })
    }
    // Волна F: точки, отклонившиеся от тренда больше чем на N σ — красные маркеры поверх ряда.
    const anomalies: { index: number; period: string; value: number; expected: number; deviation: number }[] = data.anomalies || []
    if (anomalies.length > 0) {
      series.push({
        type: 'scatter', name: 'Аномалии', symbol: 'circle', symbolSize: 12,
        itemStyle: { color: 'var(--danger)', borderColor: '#fff', borderWidth: 1 },
        data: anomalies.map((a) => [a.index, a.value]),
      })
    }
    const vals: number[] = data.values || []
    // Легенда «Значение / Тренд / Аномалии» рисуется по нижнему краю и налезала
    // на повёрнутые подписи дат. Теперь под неё резервируется место, а на низком
    // графике она вовсе скрывается: пунктир тренда и красные точки аномалий
    // различимы и без подписи, а места на подписи дат не остаётся.
    const showLegend = (data.trend || anomalies.length > 0) && fit.h >= 150
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: showLegend ? 62 : 40 },
      // Под графиком помещается только последняя пара периодов, а изменение между
      // каждой парой («22.07 → 05.08») видно здесь: наводя на точку, пользователь
      // получает и значение, и прирост к предыдущему периоду.
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const arr = Array.isArray(params) ? params : [params]
          const i = arr[0]?.dataIndex ?? 0
          const lines = [`<b>${fmtPeriod(periods[i])}</b>`]
          arr.forEach((p: any) => {
            const v = Array.isArray(p.value) ? p.value[1] : p.value
            if (v != null) lines.push(`${p.marker} ${p.seriesName}: <b>${fmt(v)}</b>`)
          })
          if (i > 0 && vals[i] != null && vals[i - 1] != null) {
            const d = vals[i] - vals[i - 1]
            const pct = vals[i - 1] ? (d / vals[i - 1]) * 100 : null
            lines.push(`<span style="color:#888">к ${fmtPeriod(periods[i - 1])}:</span> ${d >= 0 ? '+' : ''}${fmt(d)}${pct != null ? ` (${d >= 0 ? '+' : ''}${fmt(pct)}%)` : ''}`)
          }
          return lines.join('<br/>')
        },
      },
      legend: showLegend ? { bottom: 0, textStyle: { fontSize: 10 }, itemHeight: 8 } : undefined,
      xAxis: { type: 'category', data: periods.map(fmtPeriod), axisLabel: { rotate: 30, fontSize: 11 } },
      // На ужатом по высоте графике деления оси налезают друг на друга — при
      // малой высоте оставляем меньше делений.
      yAxis: { type: 'value', splitNumber: fit.h < 130 ? 3 : 5 },
      series,
    }
    const ch = data.change
    const tot = data.total_change
    // Когда точек всего две, «за весь период» и «к пред. периоду» — одно и то же число:
    // вторую строку в этом случае не показываем, чтобы не дублировать.
    const showTotal = tot != null && (data.periods_count ?? 0) > 2
    return (
      <div ref={fit.box} style={{ height: '100%' }}>
        <EChart option={opt} height={fit.h} />
        <div ref={fit.labels}>
        {ch != null && (
          <div style={{ fontSize: 12.5, marginTop: 3, lineHeight: 1.35 }}>
            К пред.
            {data.change_to_period && (
              <span style={{ color: 'var(--text-muted)' }}> ({fmtPeriod(data.change_from_period)}→{fmtPeriod(data.change_to_period)})</span>
            )}: <b style={{ color: ch >= 0 ? 'var(--success)' : 'var(--danger)' }}>{ch >= 0 ? '↑ +' : '↓ '}{fmt(ch)}{data.change_pct != null ? ` (${fmt(data.change_pct)}%)` : ''}</b>
            {data.trend_slope != null && <span style={{ marginLeft: 10, color: 'var(--warn)' }}>тренд: <b>{data.trend_slope >= 0 ? '↗ рост' : '↘ спад'}</b> ({fmt(data.trend_slope)}/период)</span>}
          </div>
        )}
        {showTotal && (
          <div style={{ fontSize: 12.5, marginTop: 1, lineHeight: 1.35 }}
            title={`${fmt(data.first_value)} на ${fmtPeriod(data.first_period)} → ${fmt(data.last_value)} на ${fmtPeriod(data.last_period)}`}>
            Всего
            <span style={{ color: 'var(--text-muted)' }}> ({fmtPeriod(data.first_period)}→{fmtPeriod(data.last_period)}, точек: {data.periods_count})</span>
            : <b style={{ color: tot >= 0 ? 'var(--success)' : 'var(--danger)' }}>{tot >= 0 ? '↑ +' : '↓ '}{fmt(tot)}{data.total_change_pct != null ? ` (${fmt(data.total_change_pct)}%)` : ''}</b>
          </div>
        )}
        {data.anomaly_threshold != null && (
          anomalies.length > 0
            ? <div style={{ fontSize: 12, marginTop: 4, color: 'var(--danger)' }}>⚠ {anomalies.length} {anomalies.length === 1 ? 'аномалия' : 'аномалии(й)'}: {anomalies.map((a) => fmtPeriod(a.period)).join(', ')}</div>
            : <div style={{ fontSize: 12, marginTop: 4, color: 'var(--text-muted)' }}>Аномалий не обнаружено (порог {data.anomaly_threshold}σ)</div>
        )}
        </div>
      </div>
    )
  }

  if (data.type === 'yoy') {
    // Год к году: текущий год (сплошная) против прошлого (пунктир) по месяцам.
    const months: string[] = data.months || []
    if (months.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const series: any[] = [] // eslint-disable-line @typescript-eslint/no-explicit-any
    if (data.previous_year != null) {
      series.push({ type: 'line', name: String(data.previous_year), data: data.previous, smooth: true, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C.prev }, lineStyle: { color: C.prev, width: 2, type: 'dashed' } })
    }
    series.push({ type: 'line', name: String(data.current_year), data: data.current, smooth: true, symbol: 'circle', symbolSize: 5,
      itemStyle: { color: C.c1 }, lineStyle: { color: C.c1, width: 2.5 }, areaStyle: { opacity: 0.08 } })
    // У «Года к году» легенда (два года) нужна всегда — резервируем под неё место,
    // иначе она ложится на подписи месяцев.
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: 56 },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      xAxis: { type: 'category', data: months, axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value' },
      series,
    }
    const ch = data.change
    return (
      <div>
        <EChart option={opt} height={196} />
        {ch != null ? (
          <div style={{ fontSize: 13, marginTop: 4 }}>
            К {data.previous_year} г. (сопоставимые месяцы: {data.compared_months}): <b style={{ color: ch >= 0 ? 'var(--success)' : 'var(--danger)' }}>
              {ch >= 0 ? '↑ +' : '↓ '}{fmt(ch)}{data.change_pct != null ? ` (${fmt(data.change_pct)}%)` : ''}{data.unit ? ` ${data.unit}` : ''}</b>
          </div>
        ) : (
          <div style={{ fontSize: 13, marginTop: 4, color: 'var(--text-muted)' }}>Нет данных за прошлый год — сравнение появится, когда будут данные двух лет.</div>
        )}
      </div>
    )
  }

  if (data.type === 'compare' || data.type === 'cross_dataset_compare') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: cats.some((c) => c.length > 6) ? 60 : 46 },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: cats.some((c) => c.length > 6) ? 30 : 0, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: (data.series || []).map((s: any, i: number) => ({
        name: s.name, type: data.viz === 'line' ? 'line' : 'bar', data: s.data,
        smooth: data.viz === 'line', itemStyle: { color: C.palette[i % C.palette.length] }, barMaxWidth: 28,
      })),
    }
    return <EChart option={opt} height={230} onPick={onPick} />
  }

  if (data.type === 'heatmap') {
    const rows: string[] = data.rows || []
    const cols: string[] = data.columns || []
    const cells: number[][] = data.cells || []
    if (rows.length === 0 || cols.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const longX = cols.some((c) => c.length > 6)
    const opt: EChartsOption = {
      tooltip: { position: 'top', formatter: (p: any) => `${cols[p.value[0]]} · ${rows[p.value[1]]}: <b>${fmt(p.value[2])}</b>` },
      grid: { left: 8, right: 12, top: 10, bottom: longX ? 58 : 44, containLabel: true },
      xAxis: { type: 'category', data: cols, splitArea: { show: true }, axisLabel: { fontSize: 11, interval: 0, rotate: longX ? 30 : 0 } },
      yAxis: { type: 'category', data: rows, splitArea: { show: true }, axisLabel: { fontSize: 11, interval: 0 } },
      visualMap: { min: data.min ?? 0, max: data.max || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
        itemHeight: 80, textStyle: { fontSize: 10 }, inRange: { color: C.heat } },
      series: [{ type: 'heatmap', data: cells, label: { show: rows.length * cols.length <= 60, fontSize: 10, formatter: (p: any) => fmt(p.value[2]) },
        emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.3)' } } }],
    }
    const h = Math.min(380, Math.max(200, rows.length * 26 + (longX ? 96 : 82)))
    return <EChart option={opt} height={h} />
  }

  if (data.type === 'pivot') {
    const cols: string[] = data.columns || []
    let rows: any[] = data.rows || []
    if (rows.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const totCell: React.CSSProperties = { ...td, fontWeight: 700, background: 'var(--surface-accent)' }
    if (pivotSearch.trim()) {
      const s = pivotSearch.trim().toLowerCase()
      rows = rows.filter((r) => String(r.row ?? '').toLowerCase().includes(s) || (r.values || []).some((v: unknown) => String(v ?? '').toLowerCase().includes(s)))
    }
    const pivotVal = (r: any, col: string) => (col === '__row' ? r.row : col === '__total' ? r.total : r.values[Number(col)])
    rows = sortRows(rows, pivotSort, pivotVal)
    return (
      <div>
        <input style={searchInput} placeholder="🔍 Поиск по сводной…" value={pivotSearch} onChange={(e) => setPivotSearch(e.target.value)} />
        <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr>
            <th style={{ ...th, ...sortableTh }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, '__row')}>Строка{sortArrow(pivotSort, '__row')}</th>
            {cols.map((c, ci) => <th key={c} style={{ ...th, ...sortableTh }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, String(ci))}>{c}{sortArrow(pivotSort, String(ci))}</th>)}
            <th style={{ ...th, ...sortableTh, color: 'var(--accent)' }} title={SORT_HINT} onClick={() => toggleSort(setPivotSort, '__total')}>Итого{sortArrow(pivotSort, '__total')}</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td style={td} colSpan={cols.length + 2}>Ничего не найдено</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                {cols.map((_, ci) => <td key={ci} style={{ ...td, textAlign: 'right' }}>{typeof r.values[ci] === 'number' ? fmt(r.values[ci]) : '—'}</td>)}
                <td style={{ ...totCell, textAlign: 'right' }}>{fmt(r.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td style={totCell}>Итого</td>
            {(data.col_totals || []).map((v: number, i: number) => <td key={i} style={{ ...totCell, textAlign: 'right' }}>{fmt(v)}</td>)}
            <td style={{ ...totCell, textAlign: 'right', color: 'var(--accent)' }}>{fmt(data.grand_total)}</td>
          </tr></tfoot>
        </table>
        </div>
      </div>
    )
  }

  if (data.type === 'waterfall') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const vals: number[] = (data.values || []).map((x: any) => (x == null ? 0 : x))
    const total = vals.reduce((a, b) => a + b, 0)
    const catAll = [...cats, data.total_label || 'Итого']
    const placeholder: number[] = []
    const bars: any[] = []
    let run = 0
    vals.forEach((x) => { placeholder.push(x >= 0 ? run : run + x); bars.push({ value: Math.abs(x), itemStyle: { color: x >= 0 ? '#0f6e56' : '#a3532d' } }); run += x })
    placeholder.push(0); bars.push({ value: total, itemStyle: { color: C.c1 } })
    const longX = catAll.some((c) => c.length > 6)
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: longX ? 56 : 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (p: any) => { const i = p[0].dataIndex; const v = i < vals.length ? vals[i] : total; return `${catAll[i]}: <b>${fmt(v)}</b>` } },
      xAxis: { type: 'category', data: catAll, axisLabel: { interval: 0, rotate: longX ? 30 : 0, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: [
        { type: 'bar', stack: 'wf', itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: placeholder, silent: true },
        { type: 'bar', stack: 'wf', data: bars, barMaxWidth: 40, label: { show: true, position: 'top', fontSize: 10, formatter: (p: any) => fmt(p.dataIndex < vals.length ? vals[p.dataIndex] : total) } },
      ],
    }
    return <EChart option={opt} height={220} />
  }

  if (data.type === 'objects_compare') {
    const cats: string[] = data.categories || []
    if (cats.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных по объектам для этого показателя</div>
    const longX = cats.some((c) => c.length > 6)
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 14, bottom: longX ? 60 : 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: longX ? 30 : 0, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', barMaxWidth: 44, label: { show: true, position: 'top', fontSize: 11, formatter: (p: any) => fmt(p.value) },
        data: (data.values || []).map((v: number, i: number) => ({ value: v, itemStyle: { color: C.palette[i % C.palette.length] } })) }],
    }
    return <EChart option={opt} height={220} onPick={onPick} />
  }

  // bar | line | pie
  if ((data.categories || []).length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
  return <EChart option={chartOption(data)} height={200} onPick={onPick} />
}

function DrillModal({ drill, onClose }: { drill: any; onClose: () => void }) {
  // Портал в body обязателен: сетка дашборда (react-grid-layout) двигает
  // виджеты CSS-трансформацией, а внутри трансформированного предка
  // position:fixed отсчитывается от НЕГО, а не от окна. Окно «подробнее»
  // оказывалось внутри карточки, обрезалось её overflow:hidden — вместе с
  // крестиком, и закрыть его было нечем.
  return createPortal((
    <div style={overlay} onClick={onClose}>
      <div style={dialog} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>Из чего собран: {drill.widget}</div>
          <button style={{ ...rmBtn, marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>

        {drill.metrics?.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={secH}>Формулы метрик</div>
            {drill.metrics.map((m: any) => (
              <div key={m.code} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{m.name} <span style={{ color: '#9aa4b2', fontWeight: 400 }}>({m.code} · v{m.version_no} · {m.status})</span></div>
                <div style={mono}>{m.formula}</div>
                {/* Расширенная информация по показателю (FR-5.9): текст модератора или заглушка */}
                {'info_text' in m && (
                  <div style={{ fontSize: 12, marginTop: 4, padding: '6px 8px', borderRadius: 6, background: m.info_text ? '#f4f7fb' : '#fafafa', color: m.info_text ? '#374151' : '#9aa4b2', whiteSpace: 'pre-wrap' }}>
                    {m.info_text ? m.info_text : 'Информации нет, в разработке.'}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div style={secH}>Первичные данные {drill.datasets?.length ? `(датасеты: ${drill.datasets.join(', ')})` : ''}</div>
        {(drill.datasets || []).length === 0 && <div style={muted}>Источники-датасеты не заданы.</div>}
        {(drill.datasets || []).map((dc: string) => {
          const t = drill.tables[dc]
          return (
            <div key={dc} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Датасет «{dc}»</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: 12, width: '100%' }}>
                  <thead><tr><th style={th}>Строка</th>
                    {t.columns.map((c: string) => (
                      <th key={c} style={th} title={c}>{t.column_titles?.[c] || c}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {t.rows.map((r: any, i: number) => (
                      <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                        {t.columns.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  ), document.body)
}

const muted: React.CSSProperties = { fontSize: 11, color: 'var(--text-faint)' }
const errBox: React.CSSProperties = { background: 'var(--danger-bg)', color: 'var(--danger)', fontSize: 12, padding: '6px 8px', borderRadius: 6 }
const th: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '4px 8px', background: 'var(--surface-2)', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid var(--border-faint)', padding: '4px 8px' }
const drillBtn: React.CSSProperties = { marginTop: 8, border: 'none', background: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12, padding: 0 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: 'var(--surface)', borderRadius: 14, padding: 22, width: 560, maxWidth: '92vw', maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
const secH: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 12, background: 'var(--surface-2)', padding: '6px 8px', borderRadius: 6, overflowX: 'auto' }
const rmBtn: React.CSSProperties = { width: 26, height: 26, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)', cursor: 'pointer', color: 'var(--text-muted)' }
