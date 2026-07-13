import { useEffect, useState } from 'react'
import {
  addHomeKpi, getHome, listMetrics, removeHomeKpi,
  type HomeData, type Metric,
} from '../api'

const KIND_ICON: Record<string, string> = { dataset: '📄', metric: '📐', dashboard: '📊' }

function fmt(n: number | null): string {
  if (n == null || !isFinite(n)) return '—'
  return Number.isInteger(n) ? n.toLocaleString('ru-RU') : n.toFixed(2)
}
function ago(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

export default function HomePage({ me, canManage, onOpenDashboard }: {
  me: { full_name: string | null; login: string }
  canManage: boolean
  onOpenDashboard: (dashboardId: string) => void
}) {
  const [data, setData] = useState<HomeData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [now, setNow] = useState(new Date())

  const load = () => getHome().then(setData).catch((e) => setError((e as Error).message))
  useEffect(() => { load(); listMetrics().then(setMetrics).catch(() => {}) }, [])
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])

  async function addKpi(code: string) {
    if (!code) return
    try { await addHomeKpi(code); load() } catch (e) { setError((e as Error).message) }
  }
  async function removeKpi(code: string) {
    try { await removeHomeKpi(code); load() } catch (e) { setError((e as Error).message) }
  }

  if (error) return <div style={errBox}>{error}</div>
  if (!data) return <div style={{ color: '#9aa4b2' }}>Загрузка…</div>

  const c = data.counters
  const counters = [
    { t: 'Дашборды', v: c.dashboards }, { t: 'Объекты', v: c.objects },
    { t: 'Метрики', v: c.metrics }, { t: 'Датасеты', v: c.datasets }, { t: 'Пользователи', v: c.users },
  ]
  const available = metrics.filter((m) => !data.key_kpis.some((k) => k.code === m.code))

  // группировка каталога по дашбордам
  const byDash: Record<string, { name: string; pages: HomeData['pages'] }> = {}
  for (const p of data.pages) {
    (byDash[p.dashboard_id] ??= { name: p.dashboard_name, pages: [] }).pages.push(p)
  }

  return (
    <div>
      {/* Приветствие + дата/время */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 20, margin: 0 }}>Здравствуйте, {me.full_name || me.login}!</h2>
        <div style={{ color: '#6b7280', fontSize: 14 }}>
          {now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })} · {now.toLocaleTimeString('ru-RU')}
        </div>
      </div>

      {/* Счётчики */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        {counters.map((x) => (
          <div key={x.t} style={counter}>
            <div style={{ fontSize: 26, fontWeight: 700, color: '#2f5496' }}>{x.v}</div>
            <div style={{ fontSize: 12, color: '#6b7280' }}>{x.t}</div>
          </div>
        ))}
      </div>

      {/* Ключевые KPI */}
      <Section title="Ключевые показатели">
        {data.key_kpis.length === 0 && <div style={muted}>Показатели ещё не выбраны{canManage ? ' — добавьте ниже.' : '.'}</div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
          {data.key_kpis.map((k) => (
            <div key={k.code} style={kpiCard}>
              <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                <div style={{ fontSize: 13, color: '#374151' }}>{k.name}</div>
                {canManage && <button style={rmBtn} onClick={() => removeKpi(k.code)} title="Убрать с главной">✕</button>}
              </div>
              {k.value != null
                ? <div style={{ fontSize: 26, fontWeight: 700, color: '#2f5496', marginTop: 4 }}>{fmt(k.value)}{k.unit && <span style={{ fontSize: 13, color: '#6b7280', marginLeft: 4 }}>{k.unit}</span>}</div>
                : <div style={{ fontSize: 12, color: '#a32d2d', marginTop: 6 }}>{k.error || 'нет значения'}</div>}
            </div>
          ))}
        </div>
        {canManage && available.length > 0 && (
          <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
            <select id="addkpi" style={sel} defaultValue="">
              <option value="" disabled>Добавить показатель…</option>
              {available.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}
            </select>
            <button style={btn} onClick={() => { const el = document.getElementById('addkpi') as HTMLSelectElement; addKpi(el.value); el.value = '' }}>＋ На главную</button>
          </div>
        )}
      </Section>

      {/* Каталог страниц */}
      <Section title="Каталог страниц">
        {data.pages.length === 0 ? <div style={muted}>Пока нет страниц дашбордов.</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(byDash).map(([did, g]) => (
              <div key={did} style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{g.name}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {g.pages.map((p) => (
                    <button key={p.page_id} style={pageChip} onClick={() => onOpenDashboard(did)} title={p.description || ''}>
                      {p.page_name} <span style={{ color: '#9aa4b2' }}>· {p.widgets} вид.</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Активность + свежесть */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <Section title="Что нового">
          {data.recent.length === 0 ? <div style={muted}>Пока нет событий.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.recent.map((r, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13 }}>
                  <span>{KIND_ICON[r.kind] || '•'}</span>
                  <span style={{ flex: 1 }}>{r.title}</span>
                  <span style={{ color: '#9aa4b2', fontSize: 12 }}>{ago(r.at)}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
        <Section title="Свежесть данных">
          {data.freshness.length === 0 ? <div style={muted}>Нет объектов.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.freshness.map((f, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13 }}>
                  <span style={{ flex: 1 }}>{f.name}</span>
                  <span style={{ color: f.last_period ? '#374151' : '#9aa4b2' }}>{f.last_period ? `данные на ${f.last_period}` : 'нет данных'}</span>
                </div>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ fontSize: 15, margin: '0 0 10px' }}>{title}</h3>
      {children}
    </div>
  )
}

const counter: React.CSSProperties = { minWidth: 96, border: '1px solid #e5e7eb', borderRadius: 12, padding: '12px 16px', textAlign: 'center' }
const kpiCard: React.CSSProperties = { border: '1px solid #e5e7eb', borderRadius: 12, padding: 12, background: '#fff' }
const pageChip: React.CSSProperties = { border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', padding: '6px 10px', fontSize: 13, cursor: 'pointer', color: '#2f5496' }
const sel: React.CSSProperties = { height: 34, padding: '0 8px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, background: '#fff' }
const btn: React.CSSProperties = { height: 34, padding: '0 12px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 13, cursor: 'pointer' }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 22, height: 22, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d', fontSize: 11 }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 14, paddingBottom: 8 }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8 }
