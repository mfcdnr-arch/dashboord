import { useEffect, useState, type FormEvent } from 'react'
import {
  createDashboard, createPage, createWidget, deletePage, deleteWidget, getDashboard,
  getDataSources, listDashboards, listPageWidgets,
  type Dashboard, type DashPage, type DataSources, type Widget,
} from '../api'
import WidgetView from './WidgetView'

const WT = [
  { v: 'kpi', t: 'KPI (число)' }, { v: 'bar', t: 'Столбцы' }, { v: 'line', t: 'Линия' },
  { v: 'pie', t: 'Круговая' }, { v: 'table', t: 'Таблица' }, { v: 'plan_fact', t: 'План-факт' },
]

export default function DashboardsPage({ canManage }: { canManage: boolean }) {
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [sel, setSel] = useState<{ dashboard: Dashboard; pages: DashPage[] } | null>(null)
  const [page, setPage] = useState<DashPage | null>(null)
  const [widgets, setWidgets] = useState<Widget[]>([])
  const [sources, setSources] = useState<DataSources | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [newDash, setNewDash] = useState('')
  const [newPage, setNewPage] = useState('')
  const [busy, setBusy] = useState(false)

  const fail = (e: unknown) => setError((e as Error).message)
  const refresh = () => listDashboards().then(setDashboards).catch(fail)

  useEffect(() => { refresh(); getDataSources().then(setSources).catch(() => setSources({ datasets: [], metrics: [] })) }, [])

  async function openDashboard(id: string) {
    setError(null); setPage(null); setWidgets([])
    try {
      const d = await getDashboard(id)
      setSel(d)
      if (d.pages.length) openPage(d.pages[0])
    } catch (e) { fail(e) }
  }
  async function openPage(p: DashPage) {
    setError(null); setPage(p)
    try { setWidgets((await listPageWidgets(p.id)).widgets) } catch (e) { fail(e) }
  }
  async function reloadPage() {
    if (page) { try { setWidgets((await listPageWidgets(page.id)).widgets) } catch (e) { fail(e) } }
  }

  async function addDashboard(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null)
    try { const d = await createDashboard(newDash.trim()); setNewDash(''); await refresh(); openDashboard(d.id) }
    catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function addPage(e: FormEvent) {
    e.preventDefault(); if (!sel) return; setBusy(true); setError(null)
    try {
      const p = await createPage(sel.dashboard.id, newPage.trim())
      setNewPage(''); const d = await getDashboard(sel.dashboard.id); setSel(d); openPage(p)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  async function delPage(p: DashPage) {
    if (!sel || !confirm(`Удалить страницу «${p.name}» со всеми виджетами?`)) return
    try { await deletePage(p.id); const d = await getDashboard(sel.dashboard.id); setSel(d); setPage(null); setWidgets([]) }
    catch (e) { fail(e) }
  }
  async function addWidget(body: { name: string; widget_type: string; config: Record<string, unknown> }) {
    if (!page) return
    try { await createWidget(page.id, body); await reloadPage(); setReloadKey((k) => k + 1) } catch (e) { fail(e) }
  }
  async function delWidget(w: Widget) {
    try { await deleteWidget(w.id); await reloadPage() } catch (e) { fail(e) }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, marginBottom: 16 }}>
        <button style={crumb} onClick={() => { setSel(null); setPage(null) }}>Дашборды</button>
        {sel && <><span style={{ color: '#9aa4b2' }}>/</span><span>{sel.dashboard.name}</span></>}
      </div>

      {error && <div style={errBox}>{error}</div>}

      {!sel && (
        <div>
          {canManage && (
            <form onSubmit={addDashboard} style={rowForm}>
              <input style={{ ...input, width: 260 }} placeholder="Название дашборда" value={newDash} onChange={(e) => setNewDash(e.target.value)} />
              <button style={btn} disabled={busy || !newDash.trim()}>＋ Дашборд</button>
            </form>
          )}
          {dashboards.length === 0 ? <div style={muted}>Пока нет дашбордов.</div> : (
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
              {dashboards.map((d, i) => (
                <div key={d.id} onClick={() => openDashboard(d.id)} style={{ ...rowItem, borderTop: i ? '1px solid #f0f0f0' : 'none' }}>
                  <span style={{ fontSize: 14 }}>{d.name}</span>
                  <span style={{ fontSize: 12, color: '#6b7280' }}>страниц: {d.pages ?? 0} · {d.publication_status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {sel && (
        <div>
          {/* Вкладки страниц */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
            {sel.pages.map((p) => (
              <button key={p.id} onClick={() => openPage(p)} style={{ ...tab, ...(page?.id === p.id ? tabActive : {}) }}>
                {p.name}
              </button>
            ))}
            {canManage && (
              <form onSubmit={addPage} style={{ display: 'flex', gap: 6 }}>
                <input style={{ ...input, height: 32, width: 150 }} placeholder="Новая страница" value={newPage} onChange={(e) => setNewPage(e.target.value)} />
                <button style={{ ...btn, height: 32 }} disabled={busy || !newPage.trim()}>＋</button>
              </form>
            )}
          </div>

          {!page ? (
            <div style={muted}>{sel.pages.length ? 'Выберите страницу.' : 'Создайте первую страницу дашборда.'}</div>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <h3 style={{ fontSize: 15, margin: 0 }}>Страница «{page.name}»</h3>
                {canManage && <button style={linkDanger} onClick={() => delPage(page)}>удалить страницу</button>}
              </div>

              {/* Сетка виджетов */}
              {widgets.length === 0 ? <div style={muted}>На странице пока нет виджетов.</div> : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
                  {widgets.map((w) => (
                    <div key={w.id} style={widgetCard}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{w.name}</div>
                        <span style={wtBadge}>{WT.find((x) => x.v === w.widget_type)?.t || w.widget_type}</span>
                        {canManage && <button style={rmBtn} onClick={() => delWidget(w)} title="Удалить">✕</button>}
                      </div>
                      <WidgetView widgetId={w.id} reloadKey={reloadKey} />
                    </div>
                  ))}
                </div>
              )}

              {canManage && sources && (
                <div style={{ marginTop: 20 }}>
                  <h3 style={{ fontSize: 14, margin: '0 0 8px' }}>Добавить виджет</h3>
                  <WidgetForm sources={sources} onCreate={addWidget} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WidgetForm({ sources, onCreate }: { sources: DataSources; onCreate: (b: { name: string; widget_type: string; config: Record<string, unknown> }) => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState('kpi')
  const [source, setSource] = useState<'metric' | 'dataset'>('metric')
  const [metricCode, setMetricCode] = useState(sources.metrics[0]?.code || '')
  const [factMetric, setFactMetric] = useState(sources.metrics[1]?.code || sources.metrics[0]?.code || '')
  const [dataset, setDataset] = useState(sources.datasets[0]?.code || '')
  const numFields = (dc: string) => (sources.datasets.find((d) => d.code === dc)?.fields.filter((f) => f.data_type === 'number') || [])
  const [valueField, setValueField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')
  const [planField, setPlanField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')
  const [factField, setFactField] = useState(numFields(sources.datasets[0]?.code || '')[0]?.code || '')

  const usesSource = type === 'kpi' || type === 'plan_fact'
  const usesDataset = (usesSource && source === 'dataset') || type === 'table' || ['bar', 'line', 'pie'].includes(type)
  const usesValueField = ['bar', 'line', 'pie'].includes(type) || (type === 'kpi' && source === 'dataset')

  function submit(e: FormEvent) {
    e.preventDefault()
    let config: Record<string, unknown> = {}
    if (type === 'kpi') config = source === 'metric' ? { metric_code: metricCode } : { dataset_code: dataset, value_field: valueField }
    else if (type === 'plan_fact') config = source === 'metric' ? { plan_metric: metricCode, fact_metric: factMetric } : { dataset_code: dataset, plan_field: planField, fact_field: factField }
    else if (type === 'table') config = { dataset_code: dataset }
    else config = { dataset_code: dataset, value_field: valueField }
    onCreate({ name: name.trim() || WT.find((x) => x.v === type)?.t || type, widget_type: type, config })
    setName('')
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', border: '1px solid #e5e7eb', borderRadius: 10, padding: 12 }}>
      <F t="Название"><input style={sel} placeholder="Заголовок виджета" value={name} onChange={(e) => setName(e.target.value)} /></F>
      <F t="Тип"><select style={sel} value={type} onChange={(e) => setType(e.target.value)}>{WT.map((x) => <option key={x.v} value={x.v}>{x.t}</option>)}</select></F>
      {usesSource && (
        <F t="Источник"><select style={sel} value={source} onChange={(e) => setSource(e.target.value as any)}>
          <option value="metric">Метрика</option><option value="dataset">Датасет</option>
        </select></F>
      )}
      {usesSource && source === 'metric' && (
        <F t={type === 'plan_fact' ? 'Метрика (план)' : 'Метрика'}><select style={sel} value={metricCode} onChange={(e) => setMetricCode(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select></F>
      )}
      {type === 'plan_fact' && source === 'metric' && (
        <F t="Метрика (факт)"><select style={sel} value={factMetric} onChange={(e) => setFactMetric(e.target.value)}>{sources.metrics.map((m) => <option key={m.code} value={m.code}>{m.name}</option>)}</select></F>
      )}
      {usesDataset && (
        <F t="Датасет"><select style={sel} value={dataset} onChange={(e) => { setDataset(e.target.value); const nf = numFields(e.target.value); setValueField(nf[0]?.code || ''); setPlanField(nf[0]?.code || ''); setFactField(nf[0]?.code || '') }}>{sources.datasets.map((d) => <option key={d.code} value={d.code}>{d.name} ({d.code})</option>)}</select></F>
      )}
      {usesValueField && (
        <F t="Поле (значение)"><select style={sel} value={valueField} onChange={(e) => setValueField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
      )}
      {type === 'plan_fact' && source === 'dataset' && (
        <>
          <F t="Поле (план)"><select style={sel} value={planField} onChange={(e) => setPlanField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
          <F t="Поле (факт)"><select style={sel} value={factField} onChange={(e) => setFactField(e.target.value)}>{numFields(dataset).map((f) => <option key={f.code} value={f.code}>{f.name}</option>)}</select></F>
        </>
      )}
      <button style={btn}>Добавить</button>
    </form>
  )
}

function F({ t, children }: { t: string; children: React.ReactNode }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: '#6b7280' }}>{t}{children}</label>
}

const crumb: React.CSSProperties = { border: 'none', background: 'none', color: '#2f5496', cursor: 'pointer', fontSize: 14, padding: 0 }
const input: React.CSSProperties = { height: 36, padding: '0 10px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14 }
const sel: React.CSSProperties = { height: 34, padding: '0 8px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 13, background: '#fff' }
const btn: React.CSSProperties = { height: 36, padding: '0 14px', border: 'none', borderRadius: 8, background: '#2f5496', color: '#fff', fontSize: 14, cursor: 'pointer' }
const rowForm: React.CSSProperties = { display: 'flex', gap: 8, marginBottom: 16 }
const rowItem: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', cursor: 'pointer' }
const tab: React.CSSProperties = { height: 34, padding: '0 14px', border: '1px solid #d1d5db', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13 }
const tabActive: React.CSSProperties = { background: '#eef', border: '1px solid #2f5496', color: '#2f5496' }
const widgetCard: React.CSSProperties = { border: '1px solid #e5e7eb', borderRadius: 12, padding: 14, background: '#fff' }
const wtBadge: React.CSSProperties = { marginLeft: 8, fontSize: 11, padding: '1px 7px', borderRadius: 8, background: '#eef', color: '#2f5496' }
const rmBtn: React.CSSProperties = { marginLeft: 'auto', width: 24, height: 24, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fff', cursor: 'pointer', color: '#a32d2d' }
const muted: React.CSSProperties = { color: '#6b7280', fontSize: 14, padding: '8px 0' }
const errBox: React.CSSProperties = { background: '#fcebeb', color: '#a32d2d', fontSize: 13, padding: '8px 10px', borderRadius: 8, marginBottom: 12 }
const linkDanger: React.CSSProperties = { border: 'none', background: 'none', color: '#a32d2d', cursor: 'pointer', fontSize: 12, padding: 0 }
