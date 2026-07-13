import { useEffect, useState } from 'react'
import { getWidgetData } from '../api'

// Отрисовка данных виджета. В 5.4 (конструктор) — лёгкий предпросмотр
// (KPI/таблица/простые бары/план-факт). Полноценные ECharts — в 5.3 (Viewer).

function fmt(n: number): string {
  if (!isFinite(n)) return '—'
  return Number.isInteger(n) ? n.toLocaleString('ru-RU') : n.toFixed(2)
}

export default function WidgetView({ widgetId, reloadKey }: { widgetId: string; reloadKey?: number }) {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null); setError(null)
    getWidgetData(widgetId).then(setData).catch((e) => setError((e as Error).message))
  }, [widgetId, reloadKey])

  if (error) return <div style={errBox}>{error}</div>
  if (!data) return <div style={{ color: '#9aa4b2', fontSize: 13 }}>Загрузка…</div>

  if (data.type === 'kpi') {
    return (
      <div>
        <div style={{ fontSize: 30, fontWeight: 700, color: '#2f5496' }}>{fmt(data.value)}
          {data.unit && <span style={{ fontSize: 15, color: '#6b7280', marginLeft: 6 }}>{data.unit}</span>}
        </div>
      </div>
    )
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
              <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: pct >= 100 ? '#0f6e56' : '#2f5496' }} />
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
          <thead><tr>
            <th style={th}>Строка</th>
            {data.columns.map((c: string) => <th key={c} style={th}>{c}</th>)}
          </tr></thead>
          <tbody>
            {data.rows.map((r: any, i: number) => (
              <tr key={i}>
                <td style={{ ...td, fontWeight: 600 }}>{r.row}</td>
                {data.columns.map((c: string) => <td key={c} style={td}>{typeof r[c] === 'number' ? fmt(r[c]) : (r[c] ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // bar | line | pie — простые горизонтальные бары (предпросмотр)
  const cats: string[] = data.categories || []
  const vals: number[] = data.values || []
  const max = Math.max(1, ...vals.map((v) => Math.abs(v)))
  const total = vals.reduce((a, b) => a + b, 0) || 1
  return (
    <div style={{ fontSize: 13 }}>
      {cats.map((c, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{ width: 90, color: '#374151', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c}</div>
          <div style={{ flex: 1, background: '#eef0f3', borderRadius: 4, height: 16, overflow: 'hidden' }}>
            <div style={{ width: `${(Math.abs(vals[i]) / max) * 100}%`, height: '100%', background: '#2f5496' }} />
          </div>
          <div style={{ width: 64, textAlign: 'right', color: '#111827' }}>
            {fmt(vals[i])}{data.type === 'pie' && <span style={{ color: '#9aa4b2' }}> ({Math.round((vals[i] / total) * 100)}%)</span>}
          </div>
        </div>
      ))}
      {cats.length === 0 && <div style={{ color: '#9aa4b2' }}>Нет данных</div>}
    </div>
  )
}

const muted: React.CSSProperties = { fontSize: 11, color: '#9aa4b2' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 12, padding: '6px 8px', borderRadius: 6 }
const th: React.CSSProperties = { border: '1px solid #eef0f3', padding: '4px 8px', background: '#f9fafb', textAlign: 'left', color: '#6b7280', fontWeight: 600 }
const td: React.CSSProperties = { border: '1px solid #eef0f3', padding: '4px 8px' }
