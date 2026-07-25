import { useEffect, useState } from 'react'
import type { EChartsOption } from 'echarts'
import { getWidgetData, getWidgetDrill } from '../api'
import EChart from './EChartLazy'

// Отрисовка данных виджета: KPI/таблица/план-факт — HTML, столбцы/линия/круговая —
// ECharts. По кнопке «подробнее» — drill (прозрачность): формула метрики + первичные строки.

function fmt(n: number): string {
  if (!isFinite(n)) return '—'
  return Number.isInteger(n) ? n.toLocaleString('ru-RU') : n.toFixed(2)
}

const PALETTE = ['#2f5496', '#4f86c6', '#7aa6d6', '#0f6e56', '#c69b2f', '#a3532d', '#6b5ca3']

function chartOption(data: any): EChartsOption {
  const cats: string[] = data.categories || []
  const vals: number[] = data.values || []
  if (data.type === 'pie') {
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{ type: 'pie', radius: ['35%', '70%'], data: cats.map((c, i) => ({ name: c, value: vals[i] })),
        label: { fontSize: 11 }, color: PALETTE }],
    }
  }
  const isLine = data.type === 'line'
  return {
    grid: { left: 40, right: 12, top: 12, bottom: cats.some((c) => c.length > 6) ? 46 : 24 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: cats, axisLabel: { interval: 0, rotate: cats.some((c) => c.length > 6) ? 30 : 0, fontSize: 11 } },
    yAxis: { type: 'value' },
    series: [{ type: isLine ? 'line' : 'bar', data: vals, smooth: isLine,
      itemStyle: { color: '#2f5496' }, lineStyle: { color: '#2f5496', width: 2 }, areaStyle: isLine ? { opacity: 0.08 } : undefined,
      barMaxWidth: 40 }],
  }
}

export default function WidgetView({ widgetId, reloadKey, showDrill = true, from, to, row, onPick }: { widgetId: string; reloadKey?: number; showDrill?: boolean; from?: string; to?: string; row?: string; onPick?: (name: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [drill, setDrill] = useState<any | null>(null)

  useEffect(() => {
    setData(null); setError(null)
    getWidgetData(widgetId, from, to, row).then(setData).catch((e) => setError((e as Error).message))
  }, [widgetId, reloadKey, from, to, row])

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
      {data && showDrill && data.type !== 'text' && data.type !== 'image' && (
        <button style={drillBtn} onClick={openDrill} title="Из чего собран показатель">🔍 подробнее</button>
      )}
      {drill && <DrillModal drill={drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

// Рендер тела виджета по готовым данным — используется в конструкторе для предпросмотра.
export function WidgetPreviewBody({ data }: { data: any }) {
  return <Body data={data} />
}

function Body({ data, onPick }: { data: any; onPick?: (name: string) => void }) {
  if (data.type === 'text') {
    const align = data.align === 'center' ? 'center' : 'left'
    if (!data.heading && !data.body) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Пустая аннотация</div>
    return (
      <div style={{ textAlign: align }}>
        {data.heading && <div style={{ fontSize: 18, fontWeight: 700, color: '#1f2937' }}>{data.heading}</div>}
        {data.body && <div style={{ fontSize: 14, color: '#374151', marginTop: data.heading ? 4 : 0, whiteSpace: 'pre-wrap' }}>{data.body}</div>}
      </div>
    )
  }
  if (data.type === 'image') {
    if (!data.url) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Не указан URL картинки</div>
    return (
      <div style={{ textAlign: 'center' }}>
        <img src={data.url} alt={data.caption || ''} style={{ maxWidth: '100%', maxHeight: 220, objectFit: data.fit === 'cover' ? 'cover' : 'contain' }} />
        {data.caption && <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{data.caption}</div>}
      </div>
    )
  }
  if (data.type === 'kpi') {
    return (
      <div style={{ fontSize: 30, fontWeight: 700, color: data.alert?.color || '#2f5496' }}>{fmt(data.value)}
        {data.unit && <span style={{ fontSize: 15, color: '#6b7280', marginLeft: 6 }}>{data.unit}</span>}
      </div>
    )
  }
  if (data.type === 'gauge') {
    const max = data.max || 100
    const color = data.alert?.color || '#2f5496'
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
    return <EChart option={opt} height={190} />
  }
  if (data.type === 'plan_fact') {
    const pct = data.pct
    return (
      <div style={{ fontSize: 14 }}>
        <div style={{ display: 'flex', gap: 18 }}>
          <div><div style={muted}>План</div><b>{fmt(data.plan)}</b></div>
          <div><div style={muted}>Факт</div><b>{fmt(data.fact)}</b></div>
          <div><div style={muted}>Δ</div><b style={{ color: data.delta >= 0 ? '#0f6e56' : '#a32d2d' }}>{data.delta >= 0 ? '+' : ''}{fmt(data.delta)}</b></div>
        </div>
        {pct != null && (
          <div style={{ marginTop: 8 }}>
            <div style={{ height: 10, background: '#eef0f3', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: data.alert?.color || (pct >= 100 ? '#0f6e56' : '#2f5496') }} />
            </div>
            <div style={{ fontSize: 13, color: '#374151', marginTop: 2 }}>Выполнение: <b>{fmt(pct)}%</b></div>
          </div>
        )}
      </div>
    )
  }
  if (data.type === 'table') {
    return (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr><th style={th}>Строка</th>{data.columns.map((c: string) => <th key={c} style={th}>{c}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((r: any, i: number) => (
              <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                {data.columns.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (data.type === 'dynamics') {
    const periods: string[] = data.periods || []
    if (periods.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных за период</div>
    const opt: EChartsOption = {
      grid: { left: 44, right: 12, top: 12, bottom: 40 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: periods, axisLabel: { rotate: 30, fontSize: 11 } },
      yAxis: { type: 'value' },
      series: [{ type: 'line', data: data.values, smooth: true, itemStyle: { color: '#2f5496' },
        lineStyle: { color: '#2f5496', width: 2 }, areaStyle: { opacity: 0.08 } }],
    }
    const ch = data.change
    return (
      <div>
        <EChart option={opt} height={180} />
        {ch != null && (
          <div style={{ fontSize: 13, marginTop: 4 }}>
            К пред. периоду: <b style={{ color: ch >= 0 ? '#0f6e56' : '#a32d2d' }}>{ch >= 0 ? '↑ +' : '↓ '}{fmt(ch)}{data.change_pct != null ? ` (${fmt(data.change_pct)}%)` : ''}</b>
          </div>
        )}
      </div>
    )
  }

  if (data.type === 'compare') {
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
        smooth: data.viz === 'line', itemStyle: { color: PALETTE[i % PALETTE.length] }, barMaxWidth: 28,
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
        itemHeight: 80, textStyle: { fontSize: 10 }, inRange: { color: ['#e6edf6', '#7aa6d6', '#2f5496', '#0f3b7a'] } },
      series: [{ type: 'heatmap', data: cells, label: { show: rows.length * cols.length <= 60, fontSize: 10, formatter: (p: any) => fmt(p.value[2]) },
        emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.3)' } } }],
    }
    const h = Math.min(380, Math.max(200, rows.length * 26 + (longX ? 96 : 82)))
    return <EChart option={opt} height={h} />
  }

  if (data.type === 'pivot') {
    const cols: string[] = data.columns || []
    const rows: any[] = data.rows || []
    if (rows.length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
    const totCell: React.CSSProperties = { ...td, fontWeight: 700, background: '#f4f7fb' }
    return (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
          <thead><tr><th style={th}>Строка</th>{cols.map((c) => <th key={c} style={th}>{c}</th>)}<th style={{ ...th, color: '#2f5496' }}>Итого</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}><td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                {cols.map((_, ci) => <td key={ci} style={{ ...td, textAlign: 'right' }}>{typeof r.values[ci] === 'number' ? fmt(r.values[ci]) : '—'}</td>)}
                <td style={{ ...totCell, textAlign: 'right' }}>{fmt(r.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td style={totCell}>Итого</td>
            {(data.col_totals || []).map((v: number, i: number) => <td key={i} style={{ ...totCell, textAlign: 'right' }}>{fmt(v)}</td>)}
            <td style={{ ...totCell, textAlign: 'right', color: '#2f5496' }}>{fmt(data.grand_total)}</td>
          </tr></tfoot>
        </table>
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
    placeholder.push(0); bars.push({ value: total, itemStyle: { color: '#2f5496' } })
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
        data: (data.values || []).map((v: number, i: number) => ({ value: v, itemStyle: { color: PALETTE[i % PALETTE.length] } })) }],
    }
    return <EChart option={opt} height={220} onPick={onPick} />
  }

  // bar | line | pie
  if ((data.categories || []).length === 0) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Нет данных</div>
  return <EChart option={chartOption(data)} height={200} onPick={onPick} />
}

function DrillModal({ drill, onClose }: { drill: any; onClose: () => void }) {
  return (
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
                  <thead><tr><th style={th}>Строка</th>{t.columns.map((c: string) => <th key={c} style={th}>{c}</th>)}</tr></thead>
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
  )
}

const muted: React.CSSProperties = { fontSize: 11, color: '#9aa4b2' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 12, padding: '6px 8px', borderRadius: 6 }
const th: React.CSSProperties = { border: '1px solid #eef0f3', padding: '4px 8px', background: '#f9fafb', textAlign: 'left', color: '#6b7280', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid #eef0f3', padding: '4px 8px' }
const drillBtn: React.CSSProperties = { marginTop: 8, border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 12, padding: 0 }
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 20 }
const dialog: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 22, width: 560, maxWidth: '92vw', maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }
const secH: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#2f5496', marginBottom: 6 }
const mono: React.CSSProperties = { fontFamily: 'ui-monospace, monospace', fontSize: 12, background: '#f9fafb', padding: '6px 8px', borderRadius: 6, overflowX: 'auto' }
const rmBtn: React.CSSProperties = { width: 26, height: 26, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#6b7280' }
